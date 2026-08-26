"""OmicsPlorer FastAPI entrypoint."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routers import (
    cohort,
    datasets,
    health,
    me,
    ontology,
    search,
    snippets,
    stats,
    translate,
)
from src.security.redaction import configure_structlog


def _allowed_origins() -> list[str]:
    """ALLOWED_ORIGINS env (CSV) — 미설정 시 dev 기본값.

    dev 기본값을 `*` 로 풀어둠 — WSL2 자동 forwarding / stale preflight cache 와
    여러 사례에서 origin 매칭이 미스매치되는 케이스 회피. allow_credentials=False
    여서 와일드카드 와 호환 (브라우저 표준이 둘이 함께 있을 때만 거부).
    prod 에선 ALLOWED_ORIGINS 환경변수로 명시 제한.
    """
    raw = os.environ.get("ALLOWED_ORIGINS", "*")
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    configure_structlog(json_output=True)
    app = FastAPI(
        title="OmicsPlorer API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,  # 토큰 헤더만 사용 — 쿠키 미사용.
        # dev 환경에서 백엔드 재시작 시 stale preflight cache 가 ACAO 누락된 응답으로
        # 굳어버리는 사례 있어 cache 짧게. prod 에선 600 으로 복원 가능.
        max_age=60,
    )
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(datasets.router, prefix="/api/v1")
    app.include_router(cohort.router, prefix="/api/v1")
    app.include_router(snippets.router, prefix="/api/v1")
    app.include_router(translate.router, prefix="/api/v1")
    app.include_router(ontology.router, prefix="/api/v1")
    app.include_router(me.router, prefix="/api/v1")
    app.include_router(stats.router, prefix="/api/v1")
    return app


app = create_app()
