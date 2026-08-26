"""[T1] Firebase Auth dependency — token 검증 + 401 경로.

본 테스트는 firebase-admin 을 모킹한다 — 실제 토큰 발급/네트워크 없음.
운영 검증은 별도 e2e 단계 (실제 Google sign-in 후 토큰 교환).
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from firebase_admin import auth as fb_auth

from src.security.firebase_auth import (
    FirebasePrincipal,
    optional_user,
    require_user,
    verify_id_token,
)


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def protected(principal: FirebasePrincipal = Depends(require_user)) -> dict:
        return {"uid": principal.uid, "email": principal.email}

    @app.get("/maybe")
    async def maybe(principal: FirebasePrincipal | None = Depends(optional_user)) -> dict:
        if principal is None:
            return {"anon": True}
        return {"uid": principal.uid}

    return app


async def _get(
    path: str,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=_make_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


# ---------------------------------------------------------------------------
# verify_id_token — 직접 호출
# ---------------------------------------------------------------------------

def test_verify_id_token_success() -> None:
    decoded = {
        "uid": "u-abc",
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice",
        "picture": "https://example/x.png",
    }
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch("firebase_admin.auth.verify_id_token", return_value=decoded):
        principal = verify_id_token("good-token")

    assert principal == FirebasePrincipal(
        uid="u-abc",
        email="alice@example.com",
        email_verified=True,
        name="Alice",
        picture="https://example/x.png",
    )


def test_verify_id_token_expired_returns_401() -> None:
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch(
             "firebase_admin.auth.verify_id_token",
             side_effect=fb_auth.ExpiredIdTokenError("expired", cause=None),
         ):
        with pytest.raises(HTTPException) as exc_info:
            verify_id_token("stale-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "id_token_expired"


def test_verify_id_token_invalid_returns_401() -> None:
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch(
             "firebase_admin.auth.verify_id_token",
             side_effect=fb_auth.InvalidIdTokenError("garbage"),
         ):
        with pytest.raises(HTTPException) as exc_info:
            verify_id_token("garbage-token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "id_token_invalid"


# ---------------------------------------------------------------------------
# require_user / optional_user — FastAPI dependency 통합
# ---------------------------------------------------------------------------

async def test_require_user_no_header_401() -> None:
    res = await _get("/protected")
    assert res.status_code == 401
    assert res.json()["detail"] == "authentication_required"
    assert "WWW-Authenticate" in res.headers


async def test_require_user_wrong_scheme_401() -> None:
    """non-Bearer scheme 도 401 로 통일 (auto_error=False + 우리 dependency 가 단일 진실)."""
    res = await _get("/protected", headers={"Authorization": "Basic deadbeef"})
    assert res.status_code == 401
    assert res.json()["detail"] == "authentication_required"


async def test_require_user_invalid_token_401() -> None:
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch(
             "firebase_admin.auth.verify_id_token",
             side_effect=fb_auth.InvalidIdTokenError("bad"),
         ):
        res = await _get("/protected", headers={"Authorization": "Bearer broken"})
    assert res.status_code == 401
    assert res.json()["detail"] == "id_token_invalid"


async def test_require_user_valid_token_passes() -> None:
    decoded = {
        "uid": "u-xyz",
        "email": "bob@example.com",
        "email_verified": True,
        "name": "Bob",
        "picture": None,
    }
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch("firebase_admin.auth.verify_id_token", return_value=decoded):
        res = await _get("/protected", headers={"Authorization": "Bearer ok"})
    assert res.status_code == 200
    assert res.json() == {"uid": "u-xyz", "email": "bob@example.com"}


async def test_optional_user_no_header_returns_anon() -> None:
    res = await _get("/maybe")
    assert res.status_code == 200
    assert res.json() == {"anon": True}


async def test_optional_user_invalid_token_falls_back_to_anon() -> None:
    """invalid 토큰을 silent fail — 익명으로 강등 (T1 timing/error 방어)."""
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch(
             "firebase_admin.auth.verify_id_token",
             side_effect=fb_auth.InvalidIdTokenError("bad"),
         ):
        res = await _get("/maybe", headers={"Authorization": "Bearer broken"})
    assert res.status_code == 200
    assert res.json() == {"anon": True}


async def test_optional_user_valid_token_returns_uid() -> None:
    decoded = {
        "uid": "u-99",
        "email": None,
        "email_verified": False,
        "name": None,
        "picture": None,
    }
    with patch("src.security.firebase_auth._ensure_admin_initialized"), \
         patch("firebase_admin.auth.verify_id_token", return_value=decoded):
        res = await _get("/maybe", headers={"Authorization": "Bearer ok"})
    assert res.status_code == 200
    assert res.json() == {"uid": "u-99"}
