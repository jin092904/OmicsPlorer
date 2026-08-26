"""Dataset detail schema — `GET /api/v1/datasets/{id}` 응답.

검색 결과(SearchResult)와 형태는 비슷하지만:
- score_breakdown 없음 (직접 조회는 검색 컨텍스트가 아님)
- abstract 는 truncate 되지 않은 full
- extraction_version, metadata_completeness 노출
- raw_metadata 는 응답에 포함하지 않음 (크기 + L0 이라도 source 의 모든 필드 노출 시 유저-인지 향상의 가치 < 응답 크기 비용)
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class DatasetDetail(BaseModel):
    dataset_id: str
    source_db: str
    source_id: str
    title: str | None
    abstract: str | None
    modality: list[str]
    organism_taxid: list[int]
    disease_ids: list[str] = []
    tissue_ids: list[str] = []
    cell_type_ids: list[str] = []
    library_strategy: str | None
    platform: str | None
    access_type: str
    has_processed_data: bool
    has_raw_data: bool
    metadata_completeness: float
    submission_date: date | None
    last_update: date | None
    n_samples: int | None
    n_subjects: int | None
    extraction_version: str
    created_at: datetime | None
    updated_at: datetime | None
