"""Health endpoints — 외부 dependency 가용성을 체크하지 않는 minimal probe."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
