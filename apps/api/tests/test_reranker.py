"""Reranker service 회귀 테스트.

실제 모델 로드는 시간/메모리 비용이 큼 — 환경변수로 RERANKER_TOP_N=0 설정 시
빠르게 disable 분기가 작동함을 검증. 실제 추론은 별도 integration 테스트로.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_module(monkeypatch):
    """각 테스트 전후로 reranker 모듈 상태 reset."""
    import src.services.reranker as r
    importlib.reload(r)
    yield
    importlib.reload(r)


def test_top_n_default(monkeypatch):
    monkeypatch.delenv("RERANKER_TOP_N", raising=False)
    import src.services.reranker as r
    assert r.rerank_top_n() == r.DEFAULT_TOP_K


def test_top_n_from_env(monkeypatch):
    monkeypatch.setenv("RERANKER_TOP_N", "5")
    import src.services.reranker as r
    importlib.reload(r)
    assert r.rerank_top_n() == 5


def test_top_n_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("RERANKER_TOP_N", "not-a-number")
    import src.services.reranker as r
    importlib.reload(r)
    assert r.rerank_top_n() == r.DEFAULT_TOP_K


def test_disabled_when_top_n_zero(monkeypatch):
    """RERANKER_TOP_N=0 → is_available False, 모델 로드 자체를 시도 안 함."""
    monkeypatch.setenv("RERANKER_TOP_N", "0")
    import src.services.reranker as r
    importlib.reload(r)
    assert r.rerank_top_n() == 0
    assert r.is_available() is False
    # disable 시 _get_model 도 None — 모델 다운로드 시도 안 함
    assert r._get_model() is None


def test_rerank_pairs_with_empty_docs(monkeypatch):
    monkeypatch.setenv("RERANKER_TOP_N", "10")
    import src.services.reranker as r
    importlib.reload(r)
    # 빈 docs 는 None — 모델 로드도 시도 안 함
    assert r.rerank_pairs("query", []) is None


def test_rerank_pairs_when_disabled(monkeypatch):
    monkeypatch.setenv("RERANKER_TOP_N", "0")
    import src.services.reranker as r
    importlib.reload(r)
    assert r.rerank_pairs("query", ["doc1", "doc2"]) is None
