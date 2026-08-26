"""GET /api/v1/datasets/{id} 회귀 테스트.

DB 가 없으면 자동 skip (DATABASE_URL 미설정).
실제 DB 연결을 사용 — datasets 테이블에서 임의 1행을 가져와 200 검증.
"""
from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def _db_reachable() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="DATABASE_URL not set")


@pytest_asyncio.fixture
async def app_client() -> httpx.AsyncClient:
    # 본 import 는 fixture 안에서 — pytest collection 시 DATABASE_URL 없는 환경에서 import 자체로 실패하지 않게.
    from src.main import app
    from src.services.dataset import get_db_engine

    # lru_cache 가 이전 테스트의 closed event loop 에 바인딩된 engine 을 들고있을 수 있음 — reset.
    get_db_engine.cache_clear()
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        # 테스트 종료 시 engine dispose — 다음 테스트는 fresh loop 에서 새 engine 을 만든다.
        try:
            eng = get_db_engine()
            await eng.dispose()
        except Exception:
            pass
        get_db_engine.cache_clear()


@pytest_asyncio.fixture
async def existing_dataset_id() -> str:
    """현재 DB 에서 임의의 dataset_id 1개 가져옴. 없으면 skip."""
    eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        async with eng.connect() as conn:
            result = await conn.execute(text("SELECT id FROM datasets LIMIT 1"))
            row = result.first()
        if row is None:
            pytest.skip("datasets 테이블이 비어 있음 — ingest 후 재실행")
        return str(row[0])
    finally:
        await eng.dispose()


@pytest.mark.asyncio
async def test_get_dataset_200(app_client: httpx.AsyncClient, existing_dataset_id: str) -> None:
    resp = await app_client.get(f"/api/v1/datasets/{existing_dataset_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dataset_id"] == existing_dataset_id
    # 핵심 필드 존재
    for key in ("source_db", "source_id", "modality", "organism_taxid",
                "access_type", "extraction_version"):
        assert key in body, f"missing field {key}"


@pytest.mark.asyncio
async def test_get_dataset_404(app_client: httpx.AsyncClient) -> None:
    bogus = uuid4()
    resp = await app_client.get(f"/api/v1/datasets/{bogus}")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "dataset not found"}


@pytest.mark.asyncio
async def test_get_dataset_422_for_malformed_uuid(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.get("/api/v1/datasets/not-a-uuid")
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    # FastAPI 의 path validation 에러는 detail 이 list[dict] — uuid_parsing 류
    assert any("uuid" in str(d).lower() for d in body["detail"])
