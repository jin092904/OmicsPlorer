"""Cohort 엔드포인트 — 코호트 분포 + 실험 디자인 도식.

GET  /datasets/{id}/cohort
    → 즉시 samples 집계 응답. cohort_design 이 NULL 이면 design=null 로 반환.
       (UI 가 design=null 일 때 별도 POST 트리거를 통해 on-demand 생성 가능)

POST /datasets/{id}/cohort/extract
    → on-demand LLM 호출. 5-10s 동기 대기. 성공 시 cohort_design 컬럼 UPSERT + 결과 반환.
       이미 추출된 경우 (cohort_design != NULL) 재추출 안 함 — 강제 재추출은 ?force=true.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from src.schemas.cohort import CohortView
from src.services.cohort import (
    fetch_cohort_view,
    get_db_engine,
    save_cohort_design,
)
from src.services.cohort_extractor import (
    COHORT_DESIGN_VERSION,
    extract_cohort_design_ondemand,
)

router = APIRouter()


@router.get("/datasets/{dataset_id}/cohort", response_model=CohortView)
async def get_cohort(dataset_id: UUID) -> CohortView:
    view = await fetch_cohort_view(dataset_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
    return CohortView.model_validate(view)


@router.post("/datasets/{dataset_id}/cohort/extract", response_model=CohortView)
async def extract_cohort(
    dataset_id: UUID,
    force: bool = Query(False, description="cohort_design 가 이미 있어도 재추출"),
) -> CohortView:
    # 데이터셋 fetch — title/abstract 가 있어야 LLM 호출 가능.
    eng = get_db_engine()
    async with eng.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, title, abstract, cohort_design
                  FROM datasets WHERE id = :id LIMIT 1
            """),
            {"id": dataset_id},
        )
        row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")

    if row["cohort_design"] is not None and not force:
        # 이미 있으면 그냥 fetch 결과 반환.
        view = await fetch_cohort_view(dataset_id)
        assert view is not None
        return CohortView.model_validate(view)

    # samples 의 disease_state 라벨 + 전체 factor 분포를 함께 input 으로 — cohort 추출
    # 정확도 향상. 특히 age/genotype 처럼 raw_attributes 키가 그룹 변수일 때 결정적.
    from src.services.cohort_samples import _label_top, fetch_sample_factors

    async with eng.connect() as conn:
        disease_dist = await _label_top(conn, dataset_id, "disease_state")
        factors = await fetch_sample_factors(conn, dataset_id)

    design = await extract_cohort_design_ondemand(
        title=row["title"],
        abstract=row["abstract"],
        condition_distribution=disease_dist or None,
        sample_factors=factors or None,
    )
    if design is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM extraction failed — try again or request batch processing",
        )

    await save_cohort_design(dataset_id, design, COHORT_DESIGN_VERSION)
    view = await fetch_cohort_view(dataset_id)
    assert view is not None
    return CohortView.model_validate(view)
