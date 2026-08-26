"""[T4] Multi-tenant 격리 — FastAPI middleware + ORM mixin.

요청 진입 시 tenant_id 를 추출하고 PostgreSQL `app.tenant_id` 세션 변수에 SET LOCAL.
이후 RLS policy 가 자동 적용된다.

미들웨어가 tenant_id를 설정하지 못하면 요청을 거부한다 — ORM 레벨에서도 mixin이
tenant_id 누락 쿼리를 reject 한다 (ADR 0002 T4).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

# TODO(verify): FastAPI starlette 의존성을 pyproject.toml 에 추가 후 실제 구현.
#
# class TenantMiddleware:
#     def __init__(self, app, header: str = "X-Tenant-Id") -> None:
#         self.app = app
#         self.header = header
#
#     async def __call__(self, scope, receive, send) -> None:
#         if scope["type"] != "http":
#             await self.app(scope, receive, send); return
#         headers = dict(scope["headers"])
#         tenant_raw = headers.get(self.header.lower().encode())
#         if not tenant_raw:
#             # 401 이 아니라 400 — Clerk JWT 미들웨어가 사전에 처리해야 함
#             await self._reject(send, "tenant_id missing")
#             return
#         try:
#             tenant_id = UUID(tenant_raw.decode())
#         except (ValueError, UnicodeDecodeError):
#             await self._reject(send, "tenant_id invalid")
#             return
#         scope["state"] = {**scope.get("state", {}), "tenant_id": tenant_id}
#         await self.app(scope, receive, send)


async def set_session_tenant(connection: Any, tenant_id: UUID) -> None:
    """psycopg/asyncpg 연결에 SET LOCAL app.tenant_id 적용.

    SQLAlchemy event listener에서 호출. 트랜잭션 시작 직후 실행되어야 한다.
    """
    raise NotImplementedError("DB 의존성 추가 후 구현 — Week 2")
