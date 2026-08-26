"""공통 pytest fixtures.

DB 접속:
    - DATABASE_URL          앱 런타임 (NOSUPERUSER, RLS 적용 대상)
    - ALEMBIC_DATABASE_URL  superuser (테스트 setup/teardown 에서 RLS 우회)

두 URL 이 모두 필요하지 않은 테스트는 해당 fixture 만 사용한다.
DB 가 미기동이거나 URL 이 미설정이면 테스트는 skip.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


@pytest.fixture(scope="session")
def app_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set — skipping DB tests")
    return url


@pytest.fixture(scope="session")
def super_db_url() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        pytest.skip("ALEMBIC_DATABASE_URL not set — skipping DB tests")
    return url


@pytest_asyncio.fixture
async def app_engine(app_db_url: str) -> AsyncIterator[AsyncEngine]:
    """NOSUPERUSER role 엔진 — RLS 가 적용된다."""
    engine = create_async_engine(app_db_url, poolclass=NullPool, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def super_engine(super_db_url: str) -> AsyncIterator[AsyncEngine]:
    """superuser 엔진 — RLS 우회. setup/teardown 전용."""
    engine = create_async_engine(super_db_url, poolclass=NullPool, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def set_tenant(conn: AsyncConnection, tenant_id: str | None) -> None:
    """현재 트랜잭션에 app.tenant_id 를 설정 (RLS 정책이 참조).

    None 이면 빈 문자열로 reset — current_setting('app.tenant_id', true) 가 빈 문자열을 반환하고,
    ::uuid 캐스트가 실패하므로 정책 평가 자체가 row 를 거부한다 (T4 가시성 0).
    """
    value = "" if tenant_id is None else str(tenant_id)
    await conn.execute(
        text("SELECT set_config('app.tenant_id', :v, true)"),
        {"v": value},
    )
