"""Orchestration: LLM 으로 free-text 라벨 추출 → OLS4 로 curie 정규화.

마스터 플랜 §5.3 의 v0 구현. 학술 사용자의 noise tolerance 가 낮으므로 OLS4 의 정확
매칭(label / exact_synonym) 만 채택 (mapper.py 참조). 정규화 실패한 텍스트는 무시 —
human review queue 는 v1+ 에서 대안.
"""
from __future__ import annotations

from src.extractors.llm_client import OllamaClient
from src.extractors.structurer import EXTRACTION_VERSION, extract_all
from src.ontology.mapper import OntologyMapper, lookup_many


async def extract_with_ontology(
    ollama: OllamaClient,
    mapper: OntologyMapper,
    title: str | None,
    abstract: str | None,
) -> dict:
    """단일 record 에 대한 통합 추출.

    반환:
        {
            "modality":      list[str],   # ALLOWED_MODALITIES
            "disease_ids":   list[str],   # MONDO:xxxxxxx
            "tissue_ids":    list[str],   # UBERON:xxxxxxx
            "cell_type_ids": list[str],   # CL:xxxxxxx
            "extraction_version": str,
        }
    """
    parts = await extract_all(ollama, title, abstract)
    diseases = await lookup_many(mapper, parts["diseases"], "mondo")
    tissues = await lookup_many(mapper, parts["tissues"], "uberon")
    cell_types = await lookup_many(mapper, parts["cell_types"], "cl")
    return {
        "modality": parts["modality"],
        "disease_ids": [m.curie for m in diseases],
        "tissue_ids": [m.curie for m in tissues],
        "cell_type_ids": [m.curie for m in cell_types],
        "extraction_version": EXTRACTION_VERSION,
    }
