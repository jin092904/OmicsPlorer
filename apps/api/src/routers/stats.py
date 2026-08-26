"""`/stats` — 랜딩 페이지의 "Database at a Glance" 데이터.

집계:
  - total_datasets / by_source: GEO/SRA/HCA/GDC 별 개수
  - extraction_progress: v0-stub vs 실 LLM 추출 비율
  - latest_datasets: 최근 submission_date 5건
  - top_modalities: GIN 인덱스로 가장 흔한 modality 5종

L0 (public) 데이터만 다루므로 인증·tenant scope 불필요. Redis 캐시 (TTL 5분) 로 부하 완화.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from sqlalchemy import text

from src.services.dataset import get_db_engine, get_redis

router = APIRouter(prefix="/stats", tags=["stats"])

logger = logging.getLogger(__name__)
CACHE_KEY = "gf:stats:landing"
CACHE_TTL = 300  # 5분


@router.get("")
async def get_stats() -> dict:
    """랜딩 페이지용 집계. 5분 캐시."""
    r = get_redis()
    if r is not None:
        try:
            cached = await r.get(CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning("redis stats get failed: %s", e)

    eng = get_db_engine()
    async with eng.connect() as conn:
        total_row = await conn.execute(
            text("SELECT COUNT(*) FROM datasets"),
        )
        total = total_row.scalar_one()

        by_source_rows = await conn.execute(
            text(
                """
                SELECT source_db, COUNT(*) AS n
                  FROM datasets
                 GROUP BY source_db
                 ORDER BY n DESC
                """
            ),
        )
        by_source = [{"source_db": r[0], "count": r[1]} for r in by_source_rows.all()]

        extraction_rows = await conn.execute(
            text(
                """
                SELECT
                  SUM(CASE WHEN extraction_version LIKE 'v0-stub%' THEN 1 ELSE 0 END) AS stub,
                  SUM(CASE WHEN extraction_version NOT LIKE 'v0-stub%' THEN 1 ELSE 0 END) AS rich
                  FROM datasets
                """
            ),
        )
        ex = extraction_rows.first()
        rich = int(ex[1] or 0)
        stub = int(ex[0] or 0)

        latest_rows = await conn.execute(
            text(
                """
                SELECT id, source_db, source_id, title, modality, organism_taxid,
                       submission_date
                  FROM datasets
                 WHERE submission_date IS NOT NULL
                 ORDER BY submission_date DESC
                 LIMIT 6
                """
            ),
        )
        latest_datasets = [
            {
                "dataset_id": str(row[0]),
                "source_db": row[1],
                "source_id": row[2],
                "title": row[3] or "",
                "modality": list(row[4] or []),
                "organism_taxid": list(row[5] or []),
                "submission_date": row[6].isoformat() if row[6] else None,
            }
            for row in latest_rows.all()
        ]

        modality_rows = await conn.execute(
            text(
                """
                SELECT m, COUNT(*) AS n
                  FROM datasets, unnest(modality) AS m
                 WHERE cardinality(modality) > 0
                 GROUP BY m
                 ORDER BY n DESC
                 LIMIT 6
                """
            ),
        )
        top_modalities = [{"value": row[0], "count": row[1]} for row in modality_rows.all()]

    payload = {
        "total_datasets": total,
        "by_source": by_source,
        "extraction": {
            "rich": rich,
            "stub": stub,
            "total": rich + stub,
            "rich_pct": round(100.0 * rich / max(rich + stub, 1), 1),
        },
        "latest_datasets": latest_datasets,
        "top_modalities": top_modalities,
    }

    if r is not None:
        try:
            await r.set(CACHE_KEY, json.dumps(payload, separators=(",", ":")), ex=CACHE_TTL)
        except Exception as e:
            logger.warning("redis stats set failed: %s", e)

    return payload
