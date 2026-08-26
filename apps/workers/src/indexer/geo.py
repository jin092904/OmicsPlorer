"""GEO indexer — esummary payload → datasets 행 UPSERT.

ETL 흐름:
    GeoHarvester.list_updated_since(since) → uid stream
    GeoHarvester.fetch_raw(uid)            → esummary payload
    index_geo_record(conn, payload, uid)   → datasets UPSERT  ← 본 모듈

본 모듈은 Celery 또는 ad-hoc script 어느 쪽에서도 호출 가능 (asyncio.run 으로 wrap).

V0 (extraction_version=`v0-stub-2026-05-06`):
- 정규 필드(source_id=accession, title, abstract=summary, n_samples, pdat) 만 채운다.
- modality / organism_taxid / disease_ids / tissue_ids / cell_type_ids / assay_ids 는 빈 배열.
- 위 필드들은 Week 3+ 의 LLM 구조화 추출 단계에서 채워진다 — extraction_version 갱신 시 재추출.
- access_type = 'open' (GEO 의 esearch 가 공개 record 만 반환하므로 안전한 기본).
- has_processed_data 는 'suppfile' 존재 여부 휴리스틱.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

EXTRACTION_VERSION = "v0-stub-2026-05-06"
SOURCE_DB = "GEO"


def _parse_pdat(pdat: str | None) -> date | None:
    """GEO 의 'YYYY/MM/DD' 문자열 → date. 알 수 없는 형식이면 None."""
    if not pdat:
        return None
    try:
        return datetime.strptime(pdat, "%Y/%m/%d").date()
    except ValueError:
        return None


def _has_processed_data_heuristic(rec: dict[str, Any]) -> bool:
    """suppfile 이 비어있지 않으면 processed 데이터가 있다고 간주."""
    suppfile = rec.get("suppfile")
    if not suppfile:
        return False
    # suppfile 은 여러 형식 (콤마/세미콜론 구분 문자열, 또는 list) 으로 올 수 있음
    if isinstance(suppfile, str):
        return bool(suppfile.strip())
    if isinstance(suppfile, list):
        return len(suppfile) > 0
    return bool(suppfile)


def _metadata_completeness(rec: dict[str, Any]) -> float:
    """0-1 사이의 단순 채움 비율 — 핵심 필드 중 비어있지 않은 비율."""
    core_fields = ("accession", "title", "summary", "taxon", "gpl", "n_samples", "pdat")
    filled = sum(1 for f in core_fields if rec.get(f))
    return round(filled / len(core_fields), 3)


def _extract_from_payload(payload: dict[str, Any], uid: str) -> dict[str, Any]:
    """esummary payload 에서 datasets 컬럼에 매핑되는 dict 를 만든다.

    ValueError: payload 가 기대 구조를 벗어났을 때.
    """
    result = payload.get("result") or {}
    rec = result.get(uid)
    if not isinstance(rec, dict):
        raise ValueError(f"esummary payload missing record for uid={uid!r}")

    accession = rec.get("accession")
    if not accession:
        raise ValueError(f"esummary record uid={uid!r} has no accession")

    pdat = _parse_pdat(rec.get("pdat"))
    n_samples = rec.get("n_samples")
    # n_samples 가 가끔 string 으로 옴 — 정수 변환
    if isinstance(n_samples, str):
        try:
            n_samples = int(n_samples)
        except ValueError:
            n_samples = None

    return {
        "source_db": SOURCE_DB,
        "source_id": accession,
        "title": rec.get("title"),
        "abstract": rec.get("summary"),
        "n_samples": n_samples,
        "access_type": "open",
        "has_processed_data": _has_processed_data_heuristic(rec),
        "has_raw_data": False,  # TODO: SRA cross-link 검사 — Week 2 SRA harvester 합류 시 보강
        "metadata_completeness": _metadata_completeness(rec),
        "platform": rec.get("gpl") or rec.get("ptechtype"),
        "library_strategy": None,  # TODO: ptechtype → library_strategy 매핑
        "submission_date": pdat,
        "last_update": pdat,
        "raw_metadata": payload,  # 원본 보존 (§5.5 멱등 재추출)
        "extraction_version": EXTRACTION_VERSION,
    }


async def index_geo_record(conn: AsyncConnection, payload: dict[str, Any], uid: str) -> str:
    """payload 를 datasets 에 UPSERT. 반환값은 GSE accession.

    멱등성: 동일 (source_db, source_id) 에 대해 두 번째 호출은 UPDATE 만 수행.
    extraction_version 이 같으면 사실상 no-op 이지만, raw_metadata 와 updated_at 은 갱신됨.
    """
    fields = _extract_from_payload(payload, uid)
    raw_metadata_json = json.dumps(fields["raw_metadata"])
    fields_for_sql = {**fields, "raw_metadata": raw_metadata_json}

    sql = text("""
        INSERT INTO datasets (
            source_db, source_id, title, abstract,
            n_samples, access_type, has_processed_data, has_raw_data,
            metadata_completeness, platform, library_strategy,
            submission_date, last_update,
            raw_metadata, extraction_version
        ) VALUES (
            :source_db, :source_id, :title, :abstract,
            :n_samples, :access_type, :has_processed_data, :has_raw_data,
            :metadata_completeness, :platform, :library_strategy,
            :submission_date, :last_update,
            CAST(:raw_metadata AS jsonb), :extraction_version
        )
        -- ON CONFLICT 는 harvest layer 의 fresh fields 만 갱신.
        -- modality / organism_taxid / disease_ids / extraction_version 은 LLM extractor 가 관리하므로
        -- harvester 가 덮어쓰지 않는다 (그러지 않으면 LLM 추출 결과가 매 harvest 마다 리셋됨).
        ON CONFLICT ON CONSTRAINT uq_datasets_source DO UPDATE SET
            title                  = EXCLUDED.title,
            abstract               = EXCLUDED.abstract,
            n_samples              = EXCLUDED.n_samples,
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
