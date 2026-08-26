"""ADR 0006 evaluation 의 search mode toggle + corpus switch 단위 테스트.

본 테스트는 *서비스 layer 호출 안 함* — schema 와 router 의 안전장치만 검증.
실 hybrid_search 의 mode 분기 동작은 통합 테스트 (evaluation/ 패키지) 에서 검증.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from src.routers.search import router as search_router
from src.schemas.search import SearchMode, SearchRequest


def _app_for_test(monkeypatch_target_module: str = "src.routers.search") -> FastAPI:
    """hybrid_search 를 in-memory stub 으로 대체한 minimal FastAPI app.

    schema validation + X-Eval-Mode 헤더 안전장치 *만* 테스트한다.
    """
    app = FastAPI()
    app.include_router(search_router, prefix="/api/v1")
    return app


async def _post(
    app: FastAPI,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/search", json=payload, headers=headers)


def test_search_mode_enum_values() -> None:
    assert SearchMode.BM25_ONLY == "bm25_only"
    assert SearchMode.DENSE_ONLY == "dense_only"
    assert SearchMode.RRF == "rrf"
    assert SearchMode.RRF_RERANK == "rrf_rerank"


def test_search_request_default_mode_is_rrf_rerank() -> None:
    req = SearchRequest(query_text="test")
    assert req.mode == SearchMode.RRF_RERANK
    assert req.corpus == "production"


def test_search_request_accepts_eval_mode() -> None:
    req = SearchRequest(query_text="test", mode="bm25_only", corpus="biocaddie_2016_eval")  # type: ignore[arg-type]
    assert req.mode == SearchMode.BM25_ONLY
    assert req.corpus == "biocaddie_2016_eval"


async def test_router_rejects_non_default_mode_without_header() -> None:
    """`mode=bm25_only` + `X-Eval-Mode` 없음 → 400 Bad Request."""
    # hybrid_search 호출되기 전에 router 가 차단해야 함 → stub 불필요.
    app = _app_for_test()
    resp = await _post(app, {"query_text": "x", "mode": "bm25_only"})
    assert resp.status_code == 400, resp.text
    assert "X-Eval-Mode" in resp.text


async def test_router_rejects_non_default_corpus_without_header() -> None:
    app = _app_for_test()
    resp = await _post(app, {"query_text": "x", "corpus": "biocaddie_2016_eval"})
    assert resp.status_code == 400
    assert "X-Eval-Mode" in resp.text


async def test_router_accepts_default_mode_without_header(monkeypatch) -> None:
    """기본 (rrf_rerank + production) 호출은 X-Eval-Mode 헤더 없이도 통과 (production 트래픽).

    hybrid_search 가 외부 (Qdrant/OpenSearch) 호출하므로 monkeypatch 로 stub.
    """
    async def stub_hybrid_search(req: dict) -> dict:
        return {
            "results": [],
            "facets": {
                "modality": [], "source_db": [], "disease_ids": [],
                "tissue_ids": [], "cell_type_ids": [],
            },
            "page": req.get("page", 1),
            "page_size": req.get("page_size", 20),
            "total_estimated": 0,
            "latency_ms": 1,
            "query_id": "test-id",
        }

    import src.routers.search as search_router_module
    monkeypatch.setattr(search_router_module, "hybrid_search", stub_hybrid_search)

    app = _app_for_test()
    resp = await _post(app, {"query_text": "x"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_estimated"] == 0


async def test_router_accepts_eval_mode_with_header(monkeypatch) -> None:
    """`mode=bm25_only` + `X-Eval-Mode: 1` 헤더 있음 → 200."""
    async def stub_hybrid_search(req: dict) -> dict:
        assert req["mode"] == "bm25_only"
        return {
            "results": [], "facets": {"modality": [], "source_db": [], "disease_ids": [],
                       "tissue_ids": [], "cell_type_ids": []},
            "page": 1, "page_size": 20, "total_estimated": 0,
            "latency_ms": 1, "query_id": "test-id",
        }

    import src.routers.search as search_router_module
    monkeypatch.setattr(search_router_module, "hybrid_search", stub_hybrid_search)

    app = _app_for_test()
    resp = await _post(
        app,
        {"query_text": "x", "mode": "bm25_only"},
        headers={"X-Eval-Mode": "1"},
    )
    assert resp.status_code == 200, resp.text
