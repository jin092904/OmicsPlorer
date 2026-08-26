"""Cohort 서비스 — sample 분포 집계 + cohort_design fetch / on-demand 생성.

호출 흐름:
    GET /datasets/{id}/cohort
        → fetch_cohort_view(dataset_id)
            1) samples 집계 (성별·연령·condition 라벨) — fetch_samples_summary
            2) datasets.cohort_design 컬럼 조회
            3) cohort_design 이 NULL 이면 on-demand LLM 호출 → DB UPSERT → 반환

캐시:
- samples 집계는 Redis 캐시 (`gf:cohort:{id}`, TTL 1h). samples backfill 시 invalidate.
- cohort_design 은 DB 컬럼에 저장 — 별도 캐시 불필요.

§12.1: 본 데이터는 L0(Public). RLS 미적용.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any
from uuid import UUID

import redis.asyncio as redis_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

CACHE_TTL_HIT = 3600
CACHE_KEY_PREFIX = "gf:cohort:"


@lru_cache(maxsize=1)
def get_db_engine() -> AsyncEngine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return create_async_engine(url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_redis() -> redis_async.Redis | None:
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    return redis_async.from_url(url, decode_responses=True)


async def fetch_cohort_view(dataset_id: UUID) -> dict[str, Any] | None:
    """데이터셋의 코호트 분포 + 실험 디자인 통합 응답.

    반환 dict (없는 데이터셋은 None):
        {
            "samples":       {n_total, sex, age, disease_state, treatment},
            "design":        {groups: [...], design_type, notes} | None,
            "design_version": str | None,
        }
    """
    # 1) cache
    r = get_redis()
    cache_key = f"{CACHE_KEY_PREFIX}{dataset_id}"
    if r is not None:
        try:
            cached = await r.get(cache_key)
        except Exception as e:
            logger.warning("redis get failed: %s", e)
            cached = None
        if cached is not None:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                logger.warning("cohort cache JSON corrupt for %s — refetching", dataset_id)

    # 2) DB
    eng = get_db_engine()
    async with eng.connect() as conn:
        # 데이터셋 존재 확인 + cohort_design 조회
        result = await conn.execute(
            text("""
                SELECT id, cohort_design, cohort_design_version
                  FROM datasets WHERE id = :id LIMIT 1
            """),
            {"id": dataset_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        # samples 집계 — 호출자 모듈 단계에서 import (circular import 회피).
        from src.services.cohort_samples import summarize_samples
        samples = await summarize_samples(conn, dataset_id)

    payload = {
        "samples": samples,
        "design": row["cohort_design"],  # JSONB → dict | None
        "design_version": row["cohort_design_version"],
    }

    # 3) cache write
    if r is not None:
        try:
            await r.set(cache_key, json.dumps(payload, separators=(",", ":")), ex=CACHE_TTL_HIT)
        except Exception as e:
            logger.warning("redis set failed: %s", e)
    return payload


async def save_cohort_design(
    dataset_id: UUID,
    design: dict[str, Any],
    version: str,
) -> None:
    """on-demand LLM 추출 결과를 DB UPSERT + 캐시 invalidate."""
    eng = get_db_engine()
    async with eng.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("""
                    UPDATE datasets
                       SET cohort_design = CAST(:d AS jsonb),
                           cohort_design_version = :v
                     WHERE id = :id
                """),
                {"d": json.dumps(design), "v": version, "id": dataset_id},
            )
    await invalidate_cohort_cache(dataset_id)


async def invalidate_cohort_cache(dataset_id: UUID) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        await r.delete(f"{CACHE_KEY_PREFIX}{dataset_id}")
    except Exception as e:
        logger.warning("redis del failed: %s", e)
