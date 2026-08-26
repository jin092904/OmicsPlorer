"""[ADR 0005] Firebase Auth ID 토큰 검증 + FastAPI dependency.

요청 흐름:
    1. 프론트가 Firebase Auth 로 Google 로그인 → ID 토큰 (~1h 유효) 발급
    2. 클라이언트가 `Authorization: Bearer <id_token>` 헤더로 백엔드 호출
    3. 본 모듈이 firebase-admin 으로 토큰 서명/만료/audience 검증
    4. 검증된 uid 가 X-Tenant-Id 와 동일한지(또는 매핑되는지) 확인 (T4 RLS 전제)

운영 노트:
    - GOOGLE_APPLICATION_CREDENTIALS 환경변수가 service-account JSON 절대경로를 가리켜야 함.
    - firebase-admin 은 process-global 싱글톤. 워커 fork 후 첫 호출에서 lazy-init.
    - 토큰 검증은 네트워크 호출 없음 (퍼블릭 키 캐시) — 평균 < 1ms.
    - 검증 실패는 401 로 통일. 5xx 로 누설 금지 (timing/key 정보 보호).
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

import firebase_admin
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

log = logging.getLogger(__name__)

_init_lock = threading.Lock()
_initialized = False


def _ensure_admin_initialized() -> None:
    """firebase-admin SDK 를 process-global 1회 초기화.

    GOOGLE_APPLICATION_CREDENTIALS 가 set 이면 그 service-account 로,
    아니면 ApplicationDefault (Cloud Run/GCE 메타데이터) 로 fallback.
    """
    global _initialized
    if _initialized:
        return
    with _init_lock:
        if _initialized:
            return
        try:
            firebase_admin.get_app()
        except ValueError:
            cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        _initialized = True


@dataclass(frozen=True)
class FirebasePrincipal:
    """검증된 Firebase 사용자.

    `uid` 는 Firebase 가 발급한 안정적 식별자 — 우리 시스템의 user_id 로 그대로 사용.
    """

    uid: str
    email: str | None
    email_verified: bool
    name: str | None
    picture: str | None


# HTTPBearer auto_error=False — 에러 메시지/포맷을 우리가 통제.
_bearer = HTTPBearer(auto_error=False)


def verify_id_token(token: str) -> FirebasePrincipal:
    """ID 토큰 검증. 실패 시 401 HTTPException."""
    _ensure_admin_initialized()
    try:
        # check_revoked=True 는 Firestore 한 번 더 호출 → latency 증가. 기본 off.
        decoded = fb_auth.verify_id_token(token)
    except fb_auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="id_token_expired",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None
    except fb_auth.RevokedIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="id_token_revoked",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None
    except (fb_auth.InvalidIdTokenError, ValueError) as exc:
        log.warning("invalid id token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="id_token_invalid",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None

    return FirebasePrincipal(
        uid=decoded["uid"],
        email=decoded.get("email"),
        email_verified=bool(decoded.get("email_verified", False)),
        name=decoded.get("name"),
        picture=decoded.get("picture"),
    )


async def require_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> FirebasePrincipal:
    """필수 인증 dependency. 토큰 없거나 무효면 401."""
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = verify_id_token(creds.credentials)
    # state 에 stash → middleware/RLS 가 동일 요청 안에서 재사용
    request.state.firebase_principal = principal
    return principal


async def optional_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> FirebasePrincipal | None:
    """선택적 인증 — 익명 검색은 허용, 로그인 시 개인화."""
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        return None
    try:
        principal = verify_id_token(creds.credentials)
    except HTTPException:
        # optional 경로에서는 무효 토큰을 익명으로 강등 (silent fail).
        return None
    request.state.firebase_principal = principal
    return principal
