"""Worker DB 엔진.

ETL/indexer 는 L0(공개 데이터) 만 다룬다. 따라서 ALEMBIC_DATABASE_URL(superuser)
또는 DATABASE_URL(앱 role) 어느 쪽도 사용 가능하다. 본 모듈은 환경변수로 노출된 URL 을
받아 단일 AsyncEngine 을 lazily 생성한다.

§12.1: L0 처리이므로 RLS·envelope encryption 적용 안 됨. tenant_id 미사용.
"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for worker tasks")
    return create_async_engine(url, future=True, pool_pre_ping=True)
