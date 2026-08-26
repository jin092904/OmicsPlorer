"""Security-specific fixtures.

`two_tenants` 는 superuser 로 두 tenant(A,B) 의 기본 데이터를 commit 하고,
테스트 종료 후 cascade DELETE 로 cleanup 한다 (FK ON DELETE CASCADE 가 users·saved_queries 등을 정리).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class TenantPair:
    a_tid: UUID
    a_uid: UUID
    a_saved_query_id: UUID
    b_tid: UUID
    b_uid: UUID
    b_saved_query_id: UUID


@pytest_asyncio.fixture
async def two_tenants(super_engine: AsyncEngine) -> AsyncIterator[TenantPair]:
    """Setup: 두 tenant(A,B) 와 각자의 user, saved_query 한 건씩 생성. superuser 로 직접 INSERT — RLS 우회.

    Teardown: tenants 만 DELETE 하면 FK CASCADE 로 모두 정리된다.
    """
    pair = TenantPair(
        a_tid=uuid4(), a_uid=uuid4(), a_saved_query_id=uuid4(),
        b_tid=uuid4(), b_uid=uuid4(), b_saved_query_id=uuid4(),
    )

    async with super_engine.connect() as conn:
        async with conn.begin():
            # Tenant A
            await conn.execute(
                text("INSERT INTO tenants(id, name, tier) VALUES (:id, :n, 'free')"),
                {"id": pair.a_tid, "n": f"TenantA-{pair.a_tid.hex[:6]}"},
            )
            await conn.execute(
                text("INSERT INTO users(id, tenant_id, clerk_id, email) "
                     "VALUES (:uid, :tid, :cid, :email)"),
                {"uid": pair.a_uid, "tid": pair.a_tid,
                 "cid": f"clerk_a_{pair.a_uid.hex[:6]}", "email": "a@test"},
            )
            await conn.execute(
                text("INSERT INTO saved_queries(id, tenant_id, user_id, name, "
                     "                         query_ciphertext, query_aad, dek_version) "
                     "VALUES (:sq, :tid, :uid, 'A query', :ct, :aad, 1)"),
                {"sq": pair.a_saved_query_id, "tid": pair.a_tid, "uid": pair.a_uid,
                 "ct": b"\x00\x01placeholder-ciphertext-for-A",
                 "aad": '{"purpose": "test", "record_id": "A"}'},
            )
            # Tenant B
            await conn.execute(
                text("INSERT INTO tenants(id, name, tier) VALUES (:id, :n, 'pro')"),
                {"id": pair.b_tid, "n": f"TenantB-{pair.b_tid.hex[:6]}"},
            )
            await conn.execute(
                text("INSERT INTO users(id, tenant_id, clerk_id, email) "
                     "VALUES (:uid, :tid, :cid, :email)"),
                {"uid": pair.b_uid, "tid": pair.b_tid,
                 "cid": f"clerk_b_{pair.b_uid.hex[:6]}", "email": "b@test"},
            )
            await conn.execute(
                text("INSERT INTO saved_queries(id, tenant_id, user_id, name, "
                     "                         query_ciphertext, query_aad, dek_version) "
                     "VALUES (:sq, :tid, :uid, 'B query', :ct, :aad, 1)"),
                {"sq": pair.b_saved_query_id, "tid": pair.b_tid, "uid": pair.b_uid,
                 "ct": b"\x00\x02placeholder-ciphertext-for-B",
                 "aad": '{"purpose": "test", "record_id": "B"}'},
            )

    try:
        yield pair
    finally:
        async with super_engine.connect() as conn:
            async with conn.begin():
                await conn.execute(
                    text("DELETE FROM tenants WHERE id IN (:a, :b)"),
                    {"a": pair.a_tid, "b": pair.b_tid},
                )
