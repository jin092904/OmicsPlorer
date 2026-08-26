"""Alembic env — async engine 사용 (asyncpg).

마이그레이션 실행 시 DATABASE_URL 환경변수에서 url 을 읽는다 (§12.10: 자격증명을 ini 에 박지 않음).
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 마이그레이션은 superuser/owner 권한이 필요하므로 ALEMBIC_DATABASE_URL 을 우선한다.
# (DATABASE_URL 은 app 런타임용 NOSUPERUSER role — DDL 권한 없음.)
db_url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)
else:
    raise RuntimeError(
        "DATABASE_URL (or ALEMBIC_DATABASE_URL) must be set. See .env.example."
    )

# 본 PR 단계: declarative model 미정. autogenerate 미사용 — 수동 작성된 migration 만 적용.
target_metadata = None


def run_migrations_offline() -> None:
    """SQL script 출력 모드."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
