"""Search 라우터 — POST /api/v1/search.

본 v0 는 인증·tenant scoping·envelope encryption 없이 동작 (L0 데이터만 검색하므로 안전).
저장된 query 는 §13.7 의 saved_queries 라우터(Week 8 도입)에서 처리.

ADR 0006 evaluation 안전장치 (2026-05):
  - `mode != rrf_rerank` 호출은 `X-Eval-Mode: 1` 헤더 필수. production 트래픽이
    실수로 비-default mode 로 호출되어 검색 품질이 저하되는 것을 차단.
  - `corpus != "production"` 도 동일 헤더 요구.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException, Query

from src.schemas.search import (
    AIPickResponse,
    SearchMode,
    SearchRequest,
    SearchResponse,
)
from src.services.ai_pick import generate_ai_pick
from src.services.search import SearchBackendUnavailable, hybrid_search

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    x_eval_mode: str | None = Header(default=None),
) -> SearchResponse:
    # Safety: non-default mode / non-production corpus 는 X-Eval-Mode 헤더 필수.
    needs_eval_header = (
        req.mode != SearchMode.RRF_RERANK or req.corpus != "production"
    )
    if needs_eval_header and not x_eval_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "mode != 'rrf_rerank' 또는 corpus != 'production' 호출은 "
                "`X-Eval-Mode: 1` 헤더가 필요합니다 (production 트래픽 보호)."
            ),
        )
    try:
        payload = await hybrid_search(req.model_dump())
    except SearchBackendUnavailable:
        # dense·lexical 둘 다 다운 — 원시 500 대신 503(일시적 장애).
        raise HTTPException(
            status_code=503,
            detail="검색 백엔드 일시 사용 불가 — 잠시 후 다시 시도해 주세요.",
        )
    # Sol 1 (query understanding) 가 다중 facet 을 하드필터로 주입하면, 태깅이 sparse 한
    # 복합 쿼리(예: "kidney and liver", "PBMC from HCC")가 0건이 될 수 있다. 0건일 때만
    # QU 없이 1회 재시도(순수 하이브리드 랭킹) → 복합 쿼리가 0건으로 죽지 않게 한다.
    # 0건일 때만 동작하므로 정상 쿼리엔 영향 없음(회귀 위험 0).
    if (payload.get("total_estimated") or 0) == 0 \
            and os.environ.get("QUERY_UNDERSTANDING_ENABLED", "0").strip() in {"1", "true", "yes", "on"}:
        try:
            retry_req = req.model_dump()
            retry_req["_skip_qu"] = True
            retry_payload = await hybrid_search(retry_req)
            if (retry_payload.get("total_estimated") or 0) > 0:
                payload = retry_payload
        except Exception:
            # 재시도 실패는 원본 0건 결과 유지(요청 전체를 500 내지 않음).
            logger.warning("0-result QU-skip retry failed; returning original payload")
    return SearchResponse.model_validate(payload)


@router.post("/ai-pick", response_model=AIPickResponse)
async def ai_pick(
    req: SearchRequest,
    nocache: bool = Query(default=False),
    x_eval_mode: str | None = Header(default=None),
) -> AIPickResponse:
    """AI's Pick — gemma4 가 검색 후보 중 0..4 개를 엄선 + 한 줄 이유.

    /search 와 동일한 X-Eval-Mode 안전장치. gemma/Redis 실패는 5xx 가 아니라
    picks=[] 로 graceful degrade (UI 가 카드를 숨김). nocache=1 → 캐시 무시 후 재생성.
    """
    needs_eval_header = (
        req.mode != SearchMode.RRF_RERANK or req.corpus != "production"
    )
    if needs_eval_header and not x_eval_mode:
        raise HTTPException(
            status_code=400,
            detail=(
                "mode != 'rrf_rerank' 또는 corpus != 'production' 호출은 "
                "`X-Eval-Mode: 1` 헤더가 필요합니다 (production 트래픽 보호)."
            ),
        )
    payload = await generate_ai_pick(req.model_dump(), nocache=nocache)
    return AIPickResponse.model_validate(payload)
