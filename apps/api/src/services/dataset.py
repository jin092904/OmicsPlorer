"""Dataset detail service — Postgres 에서 직접 조회 + Redis 캐시.

§12.1: datasets 는 L0(Public). RLS 미적용이므로 superuser 또는 app role 어느 쪽도 조회 가능.
미존재 시 None 반환 — router 가 404 변환.

Redis 캐시 (마스터 플랜 다음 단계):
- key: `gf:dataset:{uuid}`
- TTL: 1 시간 (기본). extraction_version 갱신 시 재harvest 가 자동 invalidate 하지 않으므로,
  Week 8+ 에 indexer 가 명시적으로 DEL 하도록 확장.
- value: JSON 직렬화. UUID/date/datetime 은 isoformat 문자열로.
- 404 도 캐시 (negative caching) — 짧은 TTL 60s.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from functools import lru_cache
from uuid import UUID

import redis.asyncio as redis_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

CACHE_TTL_HIT = 3600  # 1h
CACHE_TTL_MISS = 60  # 1m
CACHE_KEY_PREFIX = "gf:dataset:"
NEGATIVE_SENTINEL = "__NEG__"


@lru_cache(maxsize=1)
def get_db_engine() -> AsyncEngine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return create_async_engine(url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_redis() -> redis_async.Redis | None:
    """Redis 가 미설정이면 None — 캐시 없이 동작 (graceful degradation)."""
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    return redis_async.from_url(url, decode_responses=True)


def _json_default(obj: object) -> str:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj).__name__} not JSON-serializable")


def _serialize(row: dict) -> str:
    return json.dumps(row, default=_json_default, separators=(",", ":"))


async def _fetch_from_db(dataset_id: UUID) -> dict | None:
    eng = get_db_engine()
    async with eng.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT id, source_db, source_id, title, abstract,
                       modality, organism_taxid,
                       disease_ids, tissue_ids, cell_type_ids,
                       library_strategy, platform, access_type,
                       has_processed_data, has_raw_data, metadata_completeness,
                       submission_date, last_update,
                       n_samples, n_subjects, extraction_version,
                       created_at, updated_at
                  FROM datasets
                 WHERE id = :id
                 LIMIT 1
            """),
            {"id": dataset_id},
        )
        row = result.mappings().first()
    if row is None:
        return None
    return {
        "dataset_id": str(row["id"]),
        "source_db": row["source_db"],
        "source_id": row["source_id"],
        "title": row["title"],
        "abstract": row["abstract"],
        "modality": list(row["modality"] or []),
        "organism_taxid": list(row["organism_taxid"] or []),
        "disease_ids": list(row["disease_ids"] or []),
        "tissue_ids": list(row["tissue_ids"] or []),
        "cell_type_ids": list(row["cell_type_ids"] or []),
        "library_strategy": row["library_strategy"],
        "platform": row["platform"],
        "access_type": row["access_type"],
        "has_processed_data": bool(row["has_processed_data"]),
        "has_raw_data": bool(row["has_raw_data"]),
        "metadata_completeness": float(row["metadata_completeness"]),
        "submission_date": row["submission_date"],
        "last_update": row["last_update"],
        "n_samples": row["n_samples"],
        "n_subjects": row["n_subjects"],
        "extraction_version": row["extraction_version"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def fetch_dataset(dataset_id: UUID) -> dict | None:
    """Redis 캐시 → DB. 캐시는 hit/miss(404) 모두 저장. Redis 미가용 시 graceful degradation."""
    r = get_redis()
    cache_key = f"{CACHE_KEY_PREFIX}{dataset_id}"

    # 1) cache 조회 — 실패는 무시 (Redis 다운에도 서비스 살아있음)
    if r is not None:
        try:
            cached = await r.get(cache_key)
        except Exception as e:
            logger.warning("redis get failed: %s", e)
            cached = None
        if cached is not None:
            if cached == NEGATIVE_SENTINEL:
                return None
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                # 손상된 캐시는 무시하고 fall through
                logger.warning("redis cache JSON corrupt for %s — refetching", dataset_id)

    # 2) DB
    row = await _fetch_from_db(dataset_id)

    # 3) cache 저장
    if r is not None:
        try:
            if row is None:
                await r.set(cache_key, NEGATIVE_SENTINEL, ex=CACHE_TTL_MISS)
            else:
                await r.set(cache_key, _serialize(row), ex=CACHE_TTL_HIT)
        except Exception as e:
            logger.warning("redis set failed: %s", e)
    return row


async def invalidate_dataset_cache(dataset_id: UUID) -> None:
    """indexer / harvester 가 row 를 갱신했을 때 호출. Redis 미가용 시 no-op."""
    r = get_redis()
    if r is None:
        return
    try:
        await r.delete(f"{CACHE_KEY_PREFIX}{dataset_id}")
    except Exception as e:
        logger.warning("redis del failed: %s", e)
