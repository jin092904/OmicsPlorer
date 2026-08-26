"""DB engine + tenant 스코프 헬퍼.

두 개의 엔진:
- `app_engine()`  : NOSUPERUSER `genofinder_app` — RLS 적용 대상. 모든 사용자 요청 경로.
- `admin_engine()` : SUPERUSER `genofinder` — RLS 우회. tenant/user 부트스트랩 같은 한정 경로만.

런타임 경로는 항상 `with_tenant_scope(tenant_id)` 컨텍스트 매니저로 감싸야 한다.
SET LOCAL 은 트랜잭션 끝나면 자동 폐기 → connection pool 재활용 안전 (T4).
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


@lru_cache(maxsize=1)
def app_engine() -> AsyncEngine:
    """앱 런타임 엔진 (NOSUPERUSER)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return create_async_engine(url, future=True, pool_pre_ping=True)


@lru_cache(maxsize=1)
def admin_engine() -> AsyncEngine:
    """관리 엔진 — RLS 우회 필요한 부트스트랩 전용. ALEMBIC_DATABASE_URL 재사용."""
    url = os.environ.get("ALEMBIC_DATABASE_URL")
    if not url:
        raise RuntimeError("ALEMBIC_DATABASE_URL is required for admin operations")
    return create_async_engine(url, future=True, pool_pre_ping=True)


@asynccontextmanager
async def with_tenant_scope(tenant_id: UUID) -> AsyncIterator[AsyncConnection]:
    """`SET LOCAL app.tenant_id = '<uuid>'` 적용된 트랜잭션 연결.

    사용 예::

        async with with_tenant_scope(tid) as conn:
            res = await conn.execute(text("SELECT * FROM saved_datasets"))
    """
    eng = app_engine()
    async with eng.connect() as conn:
        async with conn.begin():
            # set_config 는 SET LOCAL 의 함수 형태 — bind 로 안전하게 값을 전달.
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            yield conn
