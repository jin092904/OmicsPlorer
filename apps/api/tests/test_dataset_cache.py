"""Redis 캐시 회귀 테스트 — gf:dataset:{id} hit/miss/negative + Redis 다운 graceful.

Redis 가 미가용 (REDIS_URL 미설정)이면 일부 테스트 자동 skip — 정확히는 'cache 가 활성화된'
경로만 검증 불가. graceful degradation 검증은 별도 케이스.
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def _redis_reachable() -> bool:
    return bool(os.environ.get("REDIS_URL"))


def _db_reachable() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


pytestmark = pytest.mark.skipif(
    not _db_reachable(), reason="DATABASE_URL not set"
)


@pytest_asyncio.fixture
async def app_client() -> httpx.AsyncClient:
    from src.main import app
    from src.services.dataset import get_db_engine, get_redis

    get_db_engine.cache_clear()
    get_redis.cache_clear()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c
    finally:
        try:
            await get_db_engine().dispose()
        except Exception:
            pass
        r = get_redis()
        if r is not None:
            try:
                await r.aclose()
            except Exception:
                pass
        get_db_engine.cache_clear()
        get_redis.cache_clear()


@pytest_asyncio.fixture
async def existing_id() -> str:
    eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with eng.connect() as conn:
            row = (await conn.execute(text("SELECT id FROM datasets LIMIT 1"))).first()
        if row is None:
            pytest.skip("datasets 비어 있음")
        return str(row[0])
    finally:
        await eng.dispose()


async def _redis_get(key: str) -> str | None:
    if not _redis_reachable():
        return None
    import redis.asyncio as redis_async

    r = redis_async.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        return await r.get(key)
    finally:
        await r.aclose()


async def _redis_del(key: str) -> None:
    if not _redis_reachable():
        return
    import redis.asyncio as redis_async

    r = redis_async.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        await r.delete(key)
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_cache_populated_after_first_hit(app_client, existing_id) -> None:
    if not _redis_reachable():
        pytest.skip("REDIS_URL not set")
    cache_key = f"gf:dataset:{existing_id}"
    await _redis_del(cache_key)
    # 첫 호출: cold — DB 에서 가져온 후 Redis 저장
    r1 = await app_client.get(f"/api/v1/datasets/{existing_id}")
    assert r1.status_code == 200
    cached = await _redis_get(cache_key)
    assert cached is not None and cached != "__NEG__"


@pytest.mark.asyncio
async def test_cache_hit_returns_same_payload(app_client, existing_id) -> None:
    if not _redis_reachable():
        pytest.skip("REDIS_URL not set")
    cache_key = f"gf:dataset:{existing_id}"
    await _redis_del(cache_key)
    r1 = await app_client.get(f"/api/v1/datasets/{existing_id}")
    r2 = await app_client.get(f"/api/v1/datasets/{existing_id}")
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json()


@pytest.mark.asyncio
async def test_negative_cache_for_404(app_client) -> None:
    if not _redis_reachable():
        pytest.skip("REDIS_URL not set")
    bogus = uuid4()
    cache_key = f"gf:dataset:{bogus}"
    await _redis_del(cache_key)
    r1 = await app_client.get(f"/api/v1/datasets/{bogus}")
    assert r1.status_code == 404
    cached = await _redis_get(cache_key)
    assert cached == "__NEG__"

    # 두 번째 호출 — DB 안 가도 동일 404 반환
    r2 = await app_client.get(f"/api/v1/datasets/{bogus}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_invalidate_dataset_cache(app_client, existing_id) -> None:
    if not _redis_reachable():
        pytest.skip("REDIS_URL not set")
    from src.services.dataset import invalidate_dataset_cache

    cache_key = f"gf:dataset:{existing_id}"
    await app_client.get(f"/api/v1/datasets/{existing_id}")  # populate
    assert await _redis_get(cache_key) is not None

    await invalidate_dataset_cache(UUID(existing_id))
    assert await _redis_get(cache_key) is None
