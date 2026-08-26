"""Source 별 watermark + lock — Redis 기반.

각 source 의 정기 task 는 watermark 를 읽어 since=watermark 로 incremental harvest 한다.
동시 실행 방지를 위해 task 시작 시 SET NX 로 lock 획득. TTL 은 task 최대 예상 시간 + 여유.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis_async

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_DAYS = 30  # watermark 가 없으면 지난 30일부터
DEFAULT_LOCK_TTL_S = 60 * 60 * 4  # 4 hours — 안전망


def _key_watermark(source: str) -> str:
    return f"gf:source_run:{source}:last_run_at"


def _key_lock(source: str) -> str:
    return f"gf:source_lock:{source}"


def _redis() -> redis_async.Redis:
    url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    return redis_async.from_url(url, decode_responses=True)


async def get_watermark(source: str) -> datetime:
    """Redis 에서 watermark 읽기. 없거나 손상이면 default backfill (-30일)."""
    r = _redis()
    try:
        try:
            raw = await r.get(_key_watermark(source))
        except Exception as e:
            logger.warning("redis get watermark failed for %s: %s", source, e)
            raw = None
    finally:
        await r.aclose()
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("watermark %r corrupted for %s — fallback to default", raw, source)
    return datetime.now(timezone.utc) - timedelta(days=DEFAULT_BACKFILL_DAYS)


async def set_watermark(source: str, when: datetime | None = None) -> None:
    when = when or datetime.now(timezone.utc)
    r = _redis()
    try:
        try:
            await r.set(_key_watermark(source), when.isoformat())
        except Exception as e:
            logger.warning("redis set watermark failed for %s: %s", source, e)
    finally:
        await r.aclose()


@asynccontextmanager
async def source_lock(source: str, ttl_s: int = DEFAULT_LOCK_TTL_S):
    """SET NX EX 로 lock 획득. 다른 task 가 이미 진행 중이면 with 본문 스킵.

    Usage:
        async with source_lock('GEO') as acquired:
            if not acquired:
                return  # 이미 다른 worker 가 진행 중
            ... do work ...
    """
    r = _redis()
    acquired = False
    try:
        try:
            ok = await r.set(_key_lock(source), "1", nx=True, ex=ttl_s)
            acquired = bool(ok)
        except Exception as e:
            logger.warning("redis lock failed for %s: %s", source, e)
            acquired = False
        yield acquired
    finally:
        # lock 해제는 best-effort. TTL 이 안전망.
        if acquired:
            try:
                await r.delete(_key_lock(source))
            except Exception:
                pass
        await r.aclose()
