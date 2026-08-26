"""[T4] Cross-tenant access regression suite.

ADR 0002 § Threat Model 의 T4 (Tenant 간 데이터 누수) 를 회귀 검증한다.
본 파일은 마스터 플랜 §12.14 #1 의 CI gate 본체이며, 실패 시 PR 머지 차단 (Week 7+).

원칙:
- 모든 테스트는 NOSUPERUSER `genofinder_app` role 로 접속해야 한다 — superuser 는 RLS 를 우회하므로
  테스트의 가치가 사라진다.
- 본 파일에서 superuser engine 은 절대 사용하지 않는다.
- conftest 의 setup 은 superuser 로 데이터를 삽입하며, RLS bypass 는 setup 단계에서만 허용된다.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import set_tenant
from tests.security.conftest import TenantPair

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# 1. 가시성 — tenant_id 없으면 0 row, 자기 tenant 만 보임
# ---------------------------------------------------------------------------

async def test_no_tenant_id_no_rows(app_engine: AsyncEngine, two_tenants: TenantPair) -> None:
    """app.tenant_id 미설정 시 RLS 가 모든 L3 row 를 숨긴다.

    current_setting('app.tenant_id', true) 가 빈 문자열이면 ::uuid 캐스트가 실패하지만,
    RLS 정책 평가는 USING expression 을 NULL 로 처리하고 row 를 거부한다.
    실제로는 정책 evaluation error 가 query 자체를 실패시킬 수 있다 — 둘 다 안전한 결과.
    """
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, None)
            try:
                result = await conn.execute(text("SELECT count(*) FROM saved_queries"))
                count = result.scalar()
                # 정책이 성공적으로 평가되어 0 rows 반환
                assert count == 0, f"tenant_id 없이 saved_queries 가 보임: count={count}"
            except (ProgrammingError, DBAPIError) as e:
                # 정책 평가가 cast error 로 실패 — 데이터 누수는 아님
                assert "uuid" in str(e).lower() or "invalid" in str(e).lower(), str(e)


async def test_tenant_a_sees_only_a(app_engine: AsyncEngine, two_tenants: TenantPair) -> None:
    """tenant A 컨텍스트에서 자기 saved_query 만 보임."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            result = await conn.execute(text("SELECT id, name FROM saved_queries ORDER BY name"))
            rows = result.fetchall()
            assert len(rows) == 1, rows
            assert rows[0].id == two_tenants.a_saved_query_id
            assert rows[0].name == "A query"


async def test_tenant_b_sees_only_b(app_engine: AsyncEngine, two_tenants: TenantPair) -> None:
    """tenant B 컨텍스트에서 자기 saved_query 만 보임 — A 의 row 는 invisible."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.b_tid)
            result = await conn.execute(text("SELECT id, name FROM saved_queries ORDER BY name"))
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0].id == two_tenants.b_saved_query_id


async def test_select_other_tenants_id_returns_nothing(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenant A 컨텍스트에서 B 의 ID 로 직접 SELECT 해도 0 row.

    ID 추측·열거 공격 방어 — RLS 가 row 자체를 hide.
    """
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            result = await conn.execute(
                text("SELECT id FROM saved_queries WHERE id = :id"),
                {"id": two_tenants.b_saved_query_id},
            )
            rows = result.fetchall()
            assert rows == []


# ---------------------------------------------------------------------------
# 2. INSERT — WITH CHECK 가 cross-tenant 행 생성을 거부
# ---------------------------------------------------------------------------

async def test_insert_for_other_tenant_blocked(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenant A 컨텍스트에서 tenant_id=B 인 행 INSERT 시 RLS WITH CHECK 가 거부."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            with pytest.raises(DBAPIError) as exc:
                await conn.execute(
                    text("INSERT INTO users(id, tenant_id, clerk_id, email) "
                         "VALUES (:uid, :tid, :cid, :email)"),
                    {"uid": uuid4(), "tid": two_tenants.b_tid,
                     "cid": f"forge_{uuid4().hex[:6]}", "email": "forge@x"},
                )
            assert "row-level security" in str(exc.value).lower()


async def test_insert_saved_query_for_other_user_blocked(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenant A 가 user_id=B's user 로 saved_query 생성 시도.

    saved_queries.tenant_id 와 user_id 가 매칭되지 않으면 FK 또는 RLS 가 거부.
    여기서는 tenant_id 자체를 B 로 강제 — RLS WITH CHECK 가 거부.
    """
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            with pytest.raises(DBAPIError) as exc:
                await conn.execute(
                    text("INSERT INTO saved_queries(id, tenant_id, user_id, name, "
                         "                         query_ciphertext, query_aad, dek_version) "
                         "VALUES (:sq, :tid, :uid, 'forge', :ct, :aad, 1)"),
                    {"sq": uuid4(), "tid": two_tenants.b_tid, "uid": two_tenants.b_uid,
                     "ct": b"\xff", "aad": '{"forge": true}'},
                )
            assert "row-level security" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 3. UPDATE / DELETE — RLS 가 cross-tenant target 을 invisible 처리
# ---------------------------------------------------------------------------

async def test_update_other_tenants_row_affects_zero(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenant A 컨텍스트에서 B 의 saved_query UPDATE 시 0 rows affected.

    ProgrammingError 가 아닌 0 rows — RLS 가 row 자체를 가리므로 WHERE 절이 매칭하지 않음.
    """
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            result = await conn.execute(
                text("UPDATE saved_queries SET name = 'HIJACKED' WHERE id = :id"),
                {"id": two_tenants.b_saved_query_id},
            )
            assert result.rowcount == 0


async def test_delete_other_tenants_row_affects_zero(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenant A 컨텍스트에서 B 의 saved_query DELETE 시 0 rows affected."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            result = await conn.execute(
                text("DELETE FROM saved_queries WHERE id = :id"),
                {"id": two_tenants.b_saved_query_id},
            )
            assert result.rowcount == 0


async def test_update_own_row_to_other_tenant_blocked(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenant A 가 자기 saved_query 의 tenant_id 를 B 로 변경 시도 → WITH CHECK 가 거부.

    UPDATE 시 RLS 는 USING (현재 가시성) + WITH CHECK (변경 후 가시성) 모두 평가한다.
    """
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            with pytest.raises(DBAPIError) as exc:
                await conn.execute(
                    text("UPDATE saved_queries SET tenant_id = :new WHERE id = :id"),
                    {"new": two_tenants.b_tid, "id": two_tenants.a_saved_query_id},
                )
            assert "row-level security" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 4. tenants 테이블 — tenant_self 정책
# ---------------------------------------------------------------------------

async def test_tenant_can_see_only_self_in_tenants_table(
    app_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """tenants 테이블은 tenant_self 정책을 사용한다 (id = current_tenant)."""
    async with app_engine.connect() as conn:
        async with conn.begin():
            await set_tenant(conn, two_tenants.a_tid)
            result = await conn.execute(text("SELECT id FROM tenants"))
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0].id == two_tenants.a_tid


# ---------------------------------------------------------------------------
# 5. Setup-time invariant — fixture 가 두 tenant 를 만든 게 superuser 측에선 보임
# ---------------------------------------------------------------------------

async def test_super_engine_sees_both_tenants(
    super_engine: AsyncEngine, two_tenants: TenantPair
) -> None:
    """sanity check — superuser 는 RLS 를 우회하므로 두 tenant 모두 본다.

    이 테스트는 fixture 가 의도대로 동작했는지만 확인하고, RLS 검증과는 무관.
    """
    async with super_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT count(*) FROM tenants WHERE id IN (:a, :b)"),
            {"a": two_tenants.a_tid, "b": two_tenants.b_tid},
        )
        assert result.scalar() == 2
