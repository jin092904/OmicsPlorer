"""Snippet 엔드포인트 — 데이터셋 다운로드 코드 스니펫.

GET /datasets/{id}/snippets
    → 해당 데이터셋의 source 에 맞는 R / Python / Bash 스니펫 리스트.

비용: pure templating (DB 1회 조회 + 메모리 연산). 캐시 불필요.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from src.services.cohort import get_db_engine
from src.services.snippets import build_snippets

router = APIRouter()


class Snippet(BaseModel):
    language: str
    title: str
    description: str
    code: str
    requires: list[str]


class SourceSnippetGroup(BaseModel):
    """하나의 source (GEO/SRA/ENA/GDC) 에 대한 스니펫 묶음."""

    source_db: str
    source_id: str
    is_primary: bool
    snippets: list[Snippet]


class SnippetsResponse(BaseModel):
    dataset_id: str
    source_db: str  # primary source (backward compat)
    source_id: str  # primary source (backward compat)
    snippets: list[Snippet]  # primary source 의 snippets (backward compat)
    sources: list[SourceSnippetGroup] = []  # 모든 source 별 그룹 (UI selector 용)


@router.get("/datasets/{dataset_id}/snippets", response_model=SnippetsResponse)
async def get_snippets(dataset_id: UUID) -> SnippetsResponse:
    eng = get_db_engine()
    async with eng.connect() as conn:
        result = await conn.execute(
            text("SELECT id, source_db, source_id FROM datasets WHERE id = :id LIMIT 1"),
            {"id": dataset_id},
        )
        row = result.mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="dataset not found")
        # dataset_sources 다중 source 조회 (없으면 primary 만)
        sources_result = await conn.execute(
            text(
                """
                SELECT source_db, source_id, is_primary
                FROM dataset_sources
                WHERE dataset_id = :id
                ORDER BY is_primary DESC, source_db ASC
                """
            ),
            {"id": dataset_id},
        )
        source_rows = sources_result.mappings().all()

    primary_db = row["source_db"]
    primary_id = row["source_id"]
    primary_snippets = [Snippet(**s) for s in build_snippets(primary_db, primary_id)]

    # 모든 source 그룹 생성. dataset_sources 에 데이터 없으면 primary 만.
    if source_rows:
        source_groups = [
            SourceSnippetGroup(
                source_db=r["source_db"],
                source_id=r["source_id"],
                is_primary=r["is_primary"],
                snippets=[Snippet(**s) for s in build_snippets(r["source_db"], r["source_id"])],
            )
            for r in source_rows
        ]
        # 빈 snippets (지원 안 되는 source) 는 제거 — UI selector 노이즈 방지
        source_groups = [g for g in source_groups if g.snippets]
    else:
        source_groups = [
            SourceSnippetGroup(
                source_db=primary_db,
                source_id=primary_id,
                is_primary=True,
                snippets=primary_snippets,
            )
        ] if primary_snippets else []

    return SnippetsResponse(
        dataset_id=str(row["id"]),
        source_db=primary_db,
        source_id=primary_id,
        snippets=primary_snippets,
        sources=source_groups,
    )
