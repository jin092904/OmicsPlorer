"""GDC indexer — project payload → datasets row.

extraction_version `v2-gdc-2026-05-06`.
GDC 모든 project 는 Homo sapiens — organism_taxid=[9606] 고정.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.ontology.mapper import OntologyMapper, lookup_many

logger = logging.getLogger(__name__)

EXTRACTION_VERSION = "v2-gdc-2026-05-06"
SOURCE_DB = "GDC"
HUMAN_TAXID = 9606

# GDC experimental_strategy → ALLOWED_MODALITIES
STRATEGY_TO_MODALITY: dict[str, str] = {
    "RNA-Seq": "bulk RNA-seq",
    "miRNA-Seq": "smallRNA-seq",
    "WGS": "WGS",
    "WXS": "WES",
    "ATAC-Seq": "ATAC-seq",
    "ChIP-Seq": "ChIP-seq",
    "Methylation Array": "methylation",
    "Bisulfite-Seq": "methylation",
    "scRNA-Seq": "scRNA-seq",
    "Targeted Sequencing": "WES",
    # 다음은 mapping 안 됨 — 통과
    # "Genotyping Array", "Reverse Phase Protein Array", "Tissue Slide", ...
}


def _quick_extract(payload: dict[str, Any]) -> dict[str, Any]:
    proj = payload.get("project") or {}
    project_id = proj.get("project_id") or proj.get("id")
    if not project_id:
        raise ValueError("GDC payload missing project_id")

    # modality from experimental_strategies
    summary = proj.get("summary") or {}
    strategies = (summary.get("experimental_strategies") or [])
    modalities: list[str] = []
    for s in strategies:
        name = (s or {}).get("experimental_strategy")
        canonical = STRATEGY_TO_MODALITY.get(name)
        if canonical and canonical not in modalities:
            modalities.append(canonical)

    primary_sites = list(dict.fromkeys(proj.get("primary_site") or []))
    disease_types = list(dict.fromkeys(proj.get("disease_type") or []))

    case_count = int(summary.get("case_count") or 0)

    # access_type — GDC project state. 개별 file 의 access 와는 다름.
    state = (proj.get("state") or "").lower()
    access_type = "open" if state == "open" else "controlled"

    return {
        "source_db": SOURCE_DB,
        "source_id": project_id,
        "title": proj.get("name") or project_id,
        "abstract": _build_abstract(proj),
        "modality": modalities,
        "organism_taxid": [HUMAN_TAXID],
        "_disease_terms": disease_types,
        "_tissue_terms": primary_sites,
        "n_samples": case_count or None,
        "access_type": access_type,
        "has_processed_data": True,
        "has_raw_data": True,
        "metadata_completeness": _completeness(proj, modalities, primary_sites, disease_types),
        "platform": None,
        "library_strategy": ", ".join(
            (s or {}).get("experimental_strategy", "") for s in strategies if s
        )[:200] or None,
        "submission_date": None,
        "last_update": None,
        "raw_metadata": payload,
        "extraction_version": EXTRACTION_VERSION,
    }


def _build_abstract(proj: dict[str, Any]) -> str | None:
    """GDC 는 별도 abstract 없음 — name + program + primary_site + disease_type 으로 합성."""
    parts: list[str] = []
    if proj.get("name"):
        parts.append(proj["name"])
    program = (proj.get("program") or {}).get("name")
    if program:
        parts.append(f"Program: {program}")
    sites = proj.get("primary_site") or []
    if sites:
        parts.append("Primary site: " + ", ".join(sites[:5]))
    diseases = proj.get("disease_type") or []
    if diseases:
        parts.append("Disease: " + ", ".join(diseases[:5]))
    return " | ".join(parts) if parts else None


def _completeness(proj, modalities, primary_sites, disease_types) -> float:
    keys = (
        bool(proj.get("name")),
        bool(modalities),
        bool(primary_sites),
        bool(disease_types),
        bool((proj.get("summary") or {}).get("case_count")),
    )
    return round(sum(keys) / len(keys), 3)


async def index_gdc_record(
    conn: AsyncConnection,
    payload: dict,
    project_id: str,
    mapper: OntologyMapper | None = None,
) -> str:
    fields = _quick_extract(payload)

    disease_ids: list[str] = []
    tissue_ids: list[str] = []
    if mapper is not None:
        disease_matches = await lookup_many(mapper, fields.pop("_disease_terms"), "mondo")
        tissue_matches = await lookup_many(mapper, fields.pop("_tissue_terms"), "uberon")
        disease_ids = [m.curie for m in disease_matches]
        tissue_ids = [m.curie for m in tissue_matches]
    else:
        fields.pop("_disease_terms", None)
        fields.pop("_tissue_terms", None)

    fields["disease_ids"] = disease_ids
    fields["tissue_ids"] = tissue_ids
    fields.setdefault("cell_type_ids", [])

    raw_metadata_json = json.dumps(fields["raw_metadata"])
    fields_for_sql = {**fields, "raw_metadata": raw_metadata_json}

    sql = text("""
        INSERT INTO datasets (
            source_db, source_id, title, abstract,
            modality, organism_taxid, disease_ids, tissue_ids, cell_type_ids,
            n_samples, access_type, has_processed_data, has_raw_data,
            metadata_completeness, platform, library_strategy,
            submission_date, last_update,
            raw_metadata, extraction_version
        ) VALUES (
            :source_db, :source_id, :title, :abstract,
            :modality, :organism_taxid, :disease_ids, :tissue_ids, :cell_type_ids,
            :n_samples, :access_type, :has_processed_data, :has_raw_data,
            :metadata_completeness, :platform, :library_strategy,
            :submission_date, :last_update,
            CAST(:raw_metadata AS jsonb), :extraction_version
        )
        ON CONFLICT ON CONSTRAINT uq_datasets_source DO UPDATE SET
            title                  = EXCLUDED.title,
            abstract               = EXCLUDED.abstract,
            modality               = EXCLUDED.modality,
            organism_taxid         = EXCLUDED.organism_taxid,
            disease_ids            = EXCLUDED.disease_ids,
            tissue_ids             = EXCLUDED.tissue_ids,
            n_samples              = EXCLUDED.n_samples,
            access_type            = EXCLUDED.access_type,
            metadata_completeness  = EXCLUDED.metadata_completeness,
            library_strategy       = EXCLUDED.library_strategy,
            raw_metadata           = EXCLUDED.raw_metadata,
            extraction_version     = EXCLUDED.extraction_version,
            updated_at             = NOW()
        RETURNING source_id
    """)
    result = await conn.execute(sql, fields_for_sql)
    return result.scalar_one()
