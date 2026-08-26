"""saved_datasets CRUD — 사용자 찜 목록.

전부 `with_tenant_scope(tenant_id)` 안에서 실행 — RLS 가 cross-tenant 차단을 보장.
JOIN 으로 datasets 의 표시용 메타데이터를 함께 반환한다 (datasets 는 L0, 모든 tenant 공통).
"""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text

from src.services.db import with_tenant_scope


async def list_saved_for_user(
    *, tenant_id: UUID, user_id: UUID, limit: int = 50
) -> list[dict]:
    async with with_tenant_scope(tenant_id) as conn:
        res = await conn.execute(
            text(
                """
                SELECT s.dataset_id,
                       s.saved_at,
                       d.source_db,
                       d.source_id,
                       d.title,
                       d.modality,
                       d.organism_taxid
                  FROM saved_datasets s
                  JOIN datasets d ON d.id = s.dataset_id
                 WHERE s.user_id = :uid
                 ORDER BY s.saved_at DESC
                 LIMIT :limit
                """
            ),
            {"uid": user_id, "limit": limit},
        )
        rows = res.mappings().all()

    return [
        {
            "dataset_id": str(r["dataset_id"]),
            "source_db": r["source_db"],
            "source_id": r["source_id"],
            "title": r["title"] or "",
            "modality": list(r["modality"] or []),
            "organism_taxid": list(r["organism_taxid"] or []),
            "saved_at": _iso(r["saved_at"]),
        }
        for r in rows
    ]


async def add_saved(
    *, tenant_id: UUID, user_id: UUID, dataset_id: UUID
) -> bool:
    """이미 찜되어 있으면 no-op (idempotent). 처음 추가했으면 True."""
    async with with_tenant_scope(tenant_id) as conn:
        res = await conn.execute(
            text(
                """
                INSERT INTO saved_datasets (tenant_id, user_id, dataset_id)
                VALUES (:tid, :uid, :did)
                ON CONFLICT (user_id, dataset_id) DO NOTHING
                RETURNING id
                """
            ),
            {"tid": tenant_id, "uid": user_id, "did": dataset_id},
        )
        return res.first() is not None


async def remove_saved(
    *, tenant_id: UUID, user_id: UUID, dataset_id: UUID
) -> bool:
    """찜 해제. 실제로 행이 사라졌으면 True, 처음부터 없었으면 False."""
    async with with_tenant_scope(tenant_id) as conn:
        res = await conn.execute(
            text(
                """
                DELETE FROM saved_datasets
                 WHERE user_id = :uid AND dataset_id = :did
                """
            ),
            {"uid": user_id, "did": dataset_id},
        )
        return (res.rowcount or 0) > 0


def _iso(v: object) -> str | None:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return None
