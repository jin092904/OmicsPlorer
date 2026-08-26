"""HCA indexer — Azul project entry → datasets row.

장점: HCA 는 organism / organ / cellType / library_construction 을 사전 정규화 제공.
LLM 추출 거의 불필요. OLS4 lookup 만 (free-text → curie) 적용.

V0 (extraction_version=`v2-hca-azul-2026-05-06`):
    source_id = HCA projectId (UUID 형태)
    title = projectShortname (>= projectTitle 보다 짧고 검색에 좋음)
    abstract = projectDescription
    organism_taxid = donorOrganisms.genusSpecies → taxid 매핑
    tissue_ids = specimens.organ → UBERON
    cell_type_ids = cellSuspensions.selectedCellType → CL
    modality = libraryConstructionApproach 정규화 (10x → scRNA-seq, etc.)
    n_samples = 추정 cell count 기반 — TODO: 더 정밀한 정의
    access_type = 'controlled' if dataUseRestriction else 'open'
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.ontology.mapper import OntologyMapper, lookup_many

logger = logging.getLogger(__name__)

EXTRACTION_VERSION = "v2-hca-azul-2026-05-06"
SOURCE_DB = "HCA"

# 흔한 species 매핑 (taxid). 그 외는 OLS4 NCBITaxon 매핑은 v2.
SPECIES_TAXID = {
    "Homo sapiens": 9606,
    "Mus musculus": 10090,
    "Rattus norvegicus": 10116,
    "Macaca mulatta": 9544,
    "Macaca fascicularis": 9541,
    "Sus scrofa": 9823,
    "Drosophila melanogaster": 7227,
    "Caenorhabditis elegans": 6239,
    "Danio rerio": 7955,
}

# library construction → modality 매핑
# HCA libraryConstructionApproach 의 대표값들을 ALLOWED_MODALITIES 로 정규화.
def _modality_from_library(library_text: str) -> list[str]:
    s = library_text.lower()
    # 단일세포 scRNA-seq 변형들
    sc_keywords = (
        "10x", "10 x", "drop-seq", "smart-seq", "smart seq", "cel-seq", "celseq",
        "mars-seq", "marsseq", "microwell-seq", "gexscope", "scrna",
        "indrop", "in-drop", "inDrop", "seq-well",
    )
    if any(k in s for k in sc_keywords):
        # ATAC scRNA 동시는 multiome — 아래 분기에서 처리
        if "atac" in s and ("multi" in s or "10x" in s):
            return ["scMultiome"]
        return ["scRNA-seq"]
    if "atac" in s and ("single" in s or "10x" in s):
        return ["scATAC-seq"]
    if "atac" in s:
        return ["ATAC-seq"]
    if "chip" in s and "seq" in s:
        return ["ChIP-seq"]
    if "ribo" in s and "seq" in s:
        return ["Ribo-seq"]
    if "cite" in s and "seq" in s:
        return ["CITE-seq"]
    if "spatial" in s or "visium" in s or "merfish" in s or "slide-seq" in s:
        return ["spatial"]
    if "rna-seq" in s or "rnaseq" in s or "rna seq" in s:
        return ["bulk RNA-seq"]
    if re.search(r"\bwgs\b|whole.genome", s):
        return ["WGS"]
    if re.search(r"\bwes\b|whole.exome", s):
        return ["WES"]
    if "methyl" in s:
        return ["methylation"]
    return []


def _flat_str_list(items: list | None) -> list[str]:
    if not items:
        return []
    out: list[str] = []
    for x in items:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    # dedup, preserve order
    return list(dict.fromkeys(out))


def _quick_extract(hit: dict[str, Any]) -> dict[str, Any]:
    """Azul hit → 우리 datasets schema 에 맞춘 중간 dict.

    OLS4 lookup 은 별도 단계 (async).
    """
    proj_list = hit.get("projects") or []
    if not proj_list:
        raise ValueError("hit has no projects[]")
    proj = proj_list[0]
    project_id = proj.get("projectId") or hit.get("entryId")
    if not project_id:
        raise ValueError("HCA hit missing projectId / entryId")

    # organism (free-text species name → taxid lookup)
    species_names: list[str] = []
    for d in (hit.get("donorOrganisms") or []):
        species_names.extend(d.get("genusSpecies") or [])
    species_names = list(dict.fromkeys(species_names))
    organism_taxid = [SPECIES_TAXID[n] for n in species_names if n in SPECIES_TAXID]

    # organ (free-text → UBERON, OLS4 lookup 필요)
    organs: list[str] = []
    for s in (hit.get("specimens") or []):
        organs.extend(s.get("organ") or [])
        organs.extend(s.get("organPart") or [])
    organs = list(dict.fromkeys(organs))

    # cell types (free-text → CL, OLS4 lookup 필요)
    cell_types: list[str] = []
    for cs in (hit.get("cellSuspensions") or []):
        cell_types.extend(cs.get("selectedCellType") or [])
    cell_types = list(dict.fromkeys(cell_types))

    # modality from library construction
    modalities: list[str] = []
    library_terms: list[str] = []
    for pr in (hit.get("protocols") or []):
        library_terms.extend(pr.get("libraryConstructionApproach") or [])
    for term in library_terms:
        for m in _modality_from_library(term):
            if m not in modalities:
                modalities.append(m)

    # platform — instrumentManufacturerModel
    platforms: list[str] = []
    for pr in (hit.get("protocols") or []):
        platforms.extend(pr.get("instrumentManufacturerModel") or [])
    platform = ", ".join(_flat_str_list(platforms)) or None

    # access — dataUseRestriction null 또는 "NRES" 면 open access 로 간주.
    # 외 "DUO" 또는 controlled 가 명시되면 controlled.
    raw_restriction = (proj.get("dataUseRestriction") or "").upper()
    if raw_restriction in {"", "NRES"}:
        access_type = "open"
    else:
        access_type = "controlled"

    # n_samples = donorCount sum (sample = donor 정의 — HCA 는 sample 의미 다양)
    donor_count = sum(int(d.get("donorCount") or 0) for d in (hit.get("donorOrganisms") or []))

    return {
        "source_db": SOURCE_DB,
        "source_id": project_id,
        "title": proj.get("projectShortname") or proj.get("projectTitle"),
        "abstract": proj.get("projectDescription"),
        "modality": modalities,
        "organism_taxid": organism_taxid,
        # tissue_ids / cell_type_ids 는 lookup 후 채워짐
        "_organ_terms": organs,
        "_cell_type_terms": cell_types,
        "n_samples": donor_count or None,
        "access_type": access_type,
        "has_processed_data": True,  # HCA 는 모든 entry 가 분석된 데이터 포함
        "has_raw_data": True,
        "metadata_completeness": _completeness(proj, organs, cell_types, library_terms),
        "platform": platform,
        "library_strategy": library_terms[0] if library_terms else None,
        "submission_date": _parse_date(hit.get("dates")),
        "last_update": _parse_date(hit.get("dates"), key="aggregateLastModifiedDate"),
        "raw_metadata": {"hit": hit},
        "extraction_version": EXTRACTION_VERSION,
    }


def _completeness(proj: dict[str, Any], organs: list[str], cell_types: list[str],
                  library_terms: list[str]) -> float:
    keys_ok = (
        bool(proj.get("projectTitle")),
        bool(proj.get("projectDescription")),
        bool(proj.get("estimatedCellCount")),
        bool(organs),
        bool(cell_types),
        bool(library_terms),
    )
    return round(sum(keys_ok) / len(keys_ok), 3)


def _parse_date(dates_list: list | None, key: str = "aggregateSubmissionDate"):
    """dates[0][key] (ISO) → date. 없으면 None."""
    if not dates_list:
        return None
    raw = (dates_list[0] or {}).get(key)
    if not raw:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


async def index_hca_record(
    conn: AsyncConnection,
    payload: dict,
    project_id: str,
    mapper: OntologyMapper | None = None,
) -> str:
    """payload['hit'] → datasets UPSERT. mapper 가 있으면 organ/cell_type 을 OLS4 로 정규화."""
    hit = payload.get("hit")
    if not hit:
        raise ValueError("payload missing 'hit'")
    fields = _quick_extract(hit)

    # OLS4 매핑 (mapper 가 None 이면 빈 리스트 — 차후 별도 step 으로 보강)
    tissue_ids: list[str] = []
    cell_type_ids: list[str] = []
    if mapper is not None:
        tissue_matches = await lookup_many(mapper, fields.pop("_organ_terms"), "uberon")
        cell_matches = await lookup_many(mapper, fields.pop("_cell_type_terms"), "cl")
        tissue_ids = [m.curie for m in tissue_matches]
        cell_type_ids = [m.curie for m in cell_matches]
    else:
        fields.pop("_organ_terms", None)
        fields.pop("_cell_type_terms", None)

    fields["tissue_ids"] = tissue_ids
    fields["cell_type_ids"] = cell_type_ids
    fields.setdefault("disease_ids", [])

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
            tissue_ids             = EXCLUDED.tissue_ids,
            cell_type_ids          = EXCLUDED.cell_type_ids,
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
            extraction_version     = EXCLUDED.extraction_version,
            updated_at             = NOW()
        RETURNING source_id
    """)
    result = await conn.execute(sql, fields_for_sql)
    return result.scalar_one()
