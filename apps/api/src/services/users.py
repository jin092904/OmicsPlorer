"""사용자 부트스트랩 — Firebase principal 을 (user_id, tenant_id) 로 매핑.

ADR 0005 v1: tenant 와 user 는 1:1. 첫 로그인 시 tenant + user 를 함께 생성한다.
조직 단위 다중 사용자 도입은 후속 ADR.

- 호출은 admin_engine (RLS 우회) 으로 수행. INSERT 가 RLS WITH CHECK 와 맞물리지 않도록.
- in-process 캐시 (firebase_uid → user_id, tenant_id) — uid→tenant 는 영구 불변.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.security.firebase_auth import FirebasePrincipal
from src.services.db import admin_engine


@dataclass(frozen=True)
class UserContext:
    """검증된 Firebase principal 의 DB 매핑."""

    user_id: UUID
    tenant_id: UUID
    nickname: str | None = None


_cache: dict[str, UserContext] = {}


async def ensure_user_for_principal(principal: FirebasePrincipal) -> UserContext:
    """firebase_uid → (user_id, tenant_id). 미존재 시 tenant + user 를 함께 생성.

    동시 첫 로그인 race 는 UNIQUE(firebase_uid) 가 보호 — 충돌 시 재SELECT.
    """
    cached = _cache.get(principal.uid)
    if cached is not None:
        return cached

    eng = admin_engine()
    ctx = await _select_existing(eng, principal.uid)

    if ctx is None:
        try:
            ctx = await _create_user_and_tenant(eng, principal)
        except IntegrityError:
            # 다른 동시 요청이 먼저 만들었음 — 재SELECT.
            ctx = await _select_existing(eng, principal.uid)
            if ctx is None:
                raise
    else:
        await _maybe_refresh_profile(eng, ctx, principal)

    _cache[principal.uid] = ctx
    return ctx


async def _select_existing(eng, firebase_uid: str) -> UserContext | None:
    async with eng.connect() as conn:
        res = await conn.execute(
            text(
                "SELECT id, tenant_id, nickname FROM users WHERE firebase_uid = :uid"
            ),
            {"uid": firebase_uid},
        )
        row = res.first()
    if row is None:
        return None
    return UserContext(user_id=row[0], tenant_id=row[1], nickname=row[2])


async def _create_user_and_tenant(eng, principal: FirebasePrincipal) -> UserContext:
    async with eng.begin() as conn:
        tenant_row = await conn.execute(
            text("INSERT INTO tenants (name, tier) VALUES (:name, 'free') RETURNING id"),
            {"name": principal.email or principal.name or principal.uid},
        )
        tenant_id = tenant_row.scalar_one()

        user_row = await conn.execute(
            text(
                """
                INSERT INTO users (tenant_id, firebase_uid, email, display_name, photo_url)
                VALUES (:tenant_id, :uid, :email, :name, :photo)
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "uid": principal.uid,
                "email": principal.email or "",
                "name": principal.name,
                "photo": principal.picture,
            },
        )
        user_id = user_row.scalar_one()
    return UserContext(user_id=user_id, tenant_id=tenant_id)


async def _maybe_refresh_profile(
    eng, ctx: UserContext, principal: FirebasePrincipal
) -> None:
    """display_name/photo_url/email 이 토큰과 다르면 갱신."""
    async with eng.begin() as conn:
        await conn.execute(
            text(
                """
                UPDATE users
                   SET email = COALESCE(NULLIF(:email, ''), email),
                       display_name = :name,
                       photo_url = :photo
                 WHERE id = :uid_pk
                   AND (
                        email IS DISTINCT FROM :email
                     OR display_name IS DISTINCT FROM :name
                     OR photo_url IS DISTINCT FROM :photo
                   )
                """
            ),
            {
                "email": principal.email or "",
                "name": principal.name,
                "photo": principal.picture,
                "uid_pk": ctx.user_id,
            },
        )


# 닉네임 길이/검증 정책. 영문/숫자/한글/공백/하이픈 허용, 양 끝 공백 trim.
NICKNAME_MAX_LEN = 32


async def update_nickname(
    *, principal: FirebasePrincipal, nickname: str | None
) -> UserContext:
    """nickname 갱신. 빈 문자열은 NULL 로 저장 (해제)."""
    cleaned: str | None = (nickname or "").strip() or None
    if cleaned is not None and len(cleaned) > NICKNAME_MAX_LEN:
        raise ValueError(f"nickname too long (max {NICKNAME_MAX_LEN})")

    ctx = await ensure_user_for_principal(principal)

    eng = admin_engine()
    async with eng.begin() as conn:
        await conn.execute(
            text("UPDATE users SET nickname = :nick WHERE id = :uid_pk"),
            {"nick": cleaned, "uid_pk": ctx.user_id},
        )

    new_ctx = UserContext(user_id=ctx.user_id, tenant_id=ctx.tenant_id, nickname=cleaned)
    _cache[principal.uid] = new_ctx
    return new_ctx
