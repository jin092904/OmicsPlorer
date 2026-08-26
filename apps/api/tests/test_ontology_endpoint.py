"""GET /api/v1/ontology/labels 회귀 테스트.

OLS4 가 reachable 한지 socket probe 후 skip.
"""
from __future__ import annotations

import socket

import httpx
import pytest
import pytest_asyncio


def _ols4_reachable() -> bool:
    try:
        with socket.create_connection(("www.ebi.ac.uk", 443), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _ols4_reachable(), reason="OLS4 not reachable")


@pytest_asyncio.fixture
async def app_client() -> httpx.AsyncClient:
    from src.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_lookup_labels_known_curies(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.get(
        "/api/v1/ontology/labels",
        params=[("ids", "MONDO:0005061"), ("ids", "CL:0000057")],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("MONDO:0005061") == "lung adenocarcinoma"
    assert body.get("CL:0000057") == "fibroblast"


@pytest.mark.asyncio
async def test_lookup_labels_unknown_curie_skipped(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.get(
        "/api/v1/ontology/labels",
        params=[("ids", "MONDO:9999999999")],
    )
    assert resp.status_code == 200
    # 매칭 실패 curie 는 응답에서 제외 (frontend 가 fallback 으로 curie 그대로 표시)
    assert "MONDO:9999999999" not in resp.json()


@pytest.mark.asyncio
async def test_lookup_labels_empty_input(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.get("/api/v1/ontology/labels")
    assert resp.status_code == 200
    assert resp.json() == {}
