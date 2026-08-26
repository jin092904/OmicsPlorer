"""SRA indexer — esummary expxml 파싱 → datasets UPSERT (study acc 단위).

V0 (extraction_version=`v0-sra-stub-2026-05-06`):
    - source_id = study accession (SRP######) — 여러 experiment 가 같은 study 면 UPSERT
    - title = study name (or experiment Title 으로 fallback)
    - organism_taxid = Organism/@taxid (정수)
    - platform = Platform/@instrument_model
    - library_strategy = LIBRARY_STRATEGY 텍스트
    - access_type = 'open' (esearch 가 public 만 반환)
    - n_samples / has_processed_data = NULL/False (Week 3 추출에서 채움)
    - raw_metadata = esummary payload 전체 보존
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

EXTRACTION_VERSION = "v0-sra-stub-2026-05-06"
SOURCE_DB = "SRA"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_expxml(expxml: str) -> dict[str, Any]:
    """expxml 안의 element 들을 dict 로 reduce.

    expxml 은 root element 가 없는 fragment 라 <root> 로 wrap 후 parse.
    """
    if not expxml:
        return {}
    try:
        root = ET.fromstring(f"<root>{expxml}</root>")
    except ET.ParseError:
        return {}
    parsed: dict[str, Any] = {}
    for elem in root:
        tag = elem.tag
        if tag == "Summary":
            title = elem.find("Title")
            if title is not None and title.text:
                parsed["title"] = title.text.strip()
            platform = elem.find("Platform")
            if platform is not None:
                parsed["platform"] = platform.attrib.get("instrument_model")
            statistics = elem.find("Statistics")
            if statistics is not None:
                # 정수만 보존 (n_samples/n_subjects 추론은 나중 단계)
                parsed["total_runs"] = _safe_int(statistics.attrib.get("total_runs"))
                parsed["total_spots"] = _safe_int(statistics.attrib.get("total_spots"))
                parsed["total_bases"] = _safe_int(statistics.attrib.get("total_bases"))
        elif tag == "Study":
            parsed["study_accession"] = elem.attrib.get("acc")
            parsed["study_name"] = elem.attrib.get("name")
        elif tag == "Experiment":
            parsed["experiment_accession"] = elem.attrib.get("acc")
            parsed["experiment_name"] = elem.attrib.get("name")
        elif tag == "Organism":
            taxid_str = elem.attrib.get("taxid")
            parsed["organism_taxid"] = _safe_int(taxid_str)
            parsed["organism_name"] = elem.attrib.get("ScientificName")
        elif tag == "Sample":
            parsed["sample_accession"] = elem.attrib.get("acc")
        elif tag == "Library_descriptor":
            for child in elem:
                if child.tag in ("LIBRARY_STRATEGY", "LIBRARY_SOURCE", "LIBRARY_SELECTION"):
                    if child.text:
                        parsed[child.tag.lower()] = child.text.strip()
        elif tag == "Submitter":
            parsed["submitter_center"] = elem.attrib.get("center_name")
    return parsed


def _safe_int(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _extract_from_payload(payload: dict[str, Any], uid: str) -> dict[str, Any]:
    result = payload.get("result") or {}
    rec = result.get(uid)
    if not isinstance(rec, dict):
        raise ValueError(f"esummary payload missing record for uid={uid!r}")

    parsed = _parse_expxml(rec.get("expxml", ""))
    study_acc = parsed.get("study_accession")
    if not study_acc:
        raise ValueError(
            f"SRA esummary uid={uid!r} has no Study/@acc in expxml — "
            "v0 indexer 는 study accession 을 source_id 로 사용한다"
        )

    organism_taxid = parsed.get("organism_taxid")
    organism_array = [organism_taxid] if isinstance(organism_taxid, int) else []

    return {
        "source_db": SOURCE_DB,
        "source_id": study_acc,
        "title": parsed.get("study_name") or parsed.get("title"),
        "abstract": None,  # SRA esummary 는 abstract 미제공 — Bioproject API 에서 후속 보강
        "organism_taxid": organism_array,
        "n_samples": None,  # study 단위 집계는 별도 step (count of experiments)
        "access_type": "open",
        "has_processed_data": False,
        "has_raw_data": True,  # SRA 는 정의상 raw reads
        "metadata_completeness": _completeness(parsed),
        "platform": parsed.get("platform"),
        "library_strategy": parsed.get("library_strategy"),
        "submission_date": _parse_date(rec.get("createdate")),
        "last_update": _parse_date(rec.get("updatedate")),
        "raw_metadata": payload,
        "extraction_version": EXTRACTION_VERSION,
    }


def _completeness(parsed: dict[str, Any]) -> float:
    keys = (
        "study_accession", "study_name", "organism_taxid",
        "platform", "library_strategy",
    )
    filled = sum(1 for k in keys if parsed.get(k))
    return round(filled / len(keys), 3)


async def index_sra_record(conn: AsyncConnection, payload: dict[str, Any], uid: str) -> str:
    fields = _extract_from_payload(payload, uid)
    raw_metadata_json = json.dumps(fields["raw_metadata"])
    fields_for_sql = {**fields, "raw_metadata": raw_metadata_json}

    sql = text("""
        INSERT INTO datasets (
            source_db, source_id, title, abstract,
            organism_taxid,
            n_samples, access_type, has_processed_data, has_raw_data,
            metadata_completeness, platform, library_strategy,
            submission_date, last_update,
            raw_metadata, extraction_version
        ) VALUES (
            :source_db, :source_id, :title, :abstract,
            :organism_taxid,
            :n_samples, :access_type, :has_processed_data, :has_raw_data,
            :metadata_completeness, :platform, :library_strategy,
            :submission_date, :last_update,
            CAST(:raw_metadata AS jsonb), :extraction_version
        )
        -- 마찬가지: extraction_version / modality 는 LLM 영역이라 harvester 가 덮어쓰지 않는다.
        -- organism_taxid 는 SRA esummary 의 expxml 에서 직접 추출하므로 harvest fresh 데이터 — 갱신 OK.
        ON CONFLICT ON CONSTRAINT uq_datasets_source DO UPDATE SET
            title                  = EXCLUDED.title,
            abstract               = EXCLUDED.abstract,
            organism_taxid         = EXCLUDED.organism_taxid,
            access_type            = EXCLUDED.access_type,
            has_processed_data     = EXCLUDED.has_processed_data,
            has_raw_data           = EXCLUDED.has_raw_data,
            metadata_completeness  = EXCLUDED.metadata_completeness,
            platform               = EXCLUDED.platform,
            library_strategy       = EXCLUDED.library_strategy,
            submission_date        = EXCLUDED.submission_date,
            last_update            = EXCLUDED.last_update,
            raw_metadata           = EXCLUDED.raw_metadata,
            updated_at             = NOW()
        RETURNING source_id
    """)
    result = await conn.execute(sql, fields_for_sql)
    return result.scalar_one()
