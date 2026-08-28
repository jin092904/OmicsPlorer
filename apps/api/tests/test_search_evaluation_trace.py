"""Fail-closed execution-trace tests for frozen retrieval evaluation."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from src.services import search as search_service


class _FakeQdrant:
    def __init__(self, **_: Any) -> None:
        pass

    async def close(self) -> None:
        pass


class _FakeOpenSearch:
    def __init__(self, **_: Any) -> None:
        pass

    async def search(self, **_: Any) -> dict[str, Any]:
        return {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_id": "00000000-0000-0000-0000-000000000001",
                        "_score": 3.5,
                        "_source": {
                            "source_db": "GEO",
                            "source_id": "GSE1",
                            "title": "synthetic test record",
                            "organism_taxid": [9606],
                            "access_type": "open",
                        },
                    }
                ],
            }
        }

    async def close(self) -> None:
        pass


@pytest.fixture
def effective_config(tmp_path, monkeypatch) -> str:
    path = tmp_path / "effective-server-config.json"
    path.write_text('{"z":2,"a":1}\n', encoding="utf-8")
    monkeypatch.setenv("EFFECTIVE_SERVER_CONFIG_PATH", str(path))
    search_service._canonical_json_file_sha256.cache_clear()
    return hashlib.sha256(b'{"a":1,"z":2}').hexdigest()


def test_effective_config_digest_uses_canonical_parsed_json(effective_config: str) -> None:
    assert search_service._effective_configuration_sha256() == effective_config


def test_trace_state_derives_effective_mode_from_used_components() -> None:
    trace = search_service._EvaluationTraceState(
        enabled=True,
        requested_mode="rrf_rerank",
    )
    trace.lexical = "used"
    trace.dense = "used"
    trace.reranker = "used"
    assert trace.effective_mode() == "rrf_rerank"

    trace.dense = "failed"
    assert trace.effective_mode() == "bm25_rerank"


async def test_bm25_eval_trace_records_effective_path(
    effective_config: str,
    monkeypatch,
) -> None:
    monkeypatch.setattr(search_service, "AsyncQdrantClient", _FakeQdrant)
    monkeypatch.setattr(search_service, "AsyncOpenSearch", _FakeOpenSearch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("QUERY_UNDERSTANDING_ENABLED", "0")

    response = await search_service.hybrid_search(
        {
            "query_text": "human transcriptome",
            "mode": "bm25_only",
            "page": 1,
            "page_size": 20,
            "auto_translate": True,
            "_evaluation_trace": True,
        }
    )

    trace = response["evaluation_trace"]
    assert trace == {
        "requested_mode": "bm25_only",
        "effective_mode": "bm25_only",
        "configuration_sha256": effective_config,
        "components": {
            "lexical": "used",
            "dense": "not_requested",
            "reranker": "not_requested",
            "translation": "not_needed",
            "query_understanding": "disabled",
            "accession_shortcut": {"enabled": True, "applied": False},
            "cardinality_boost": {"enabled": True, "applied": False},
        },
        "fallbacks": [],
    }


async def test_dense_failure_is_not_relabelled_as_requested_mode(
    effective_config: str,
    monkeypatch,
) -> None:
    async def fail_embedding(_: str) -> list[float]:
        raise RuntimeError("synthetic dense failure")

    monkeypatch.setattr(search_service, "AsyncQdrantClient", _FakeQdrant)
    monkeypatch.setattr(search_service, "AsyncOpenSearch", _FakeOpenSearch)
    monkeypatch.setattr(search_service, "_embed_query", fail_embedding)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)

    response = await search_service.hybrid_search(
        {
            "query_text": "human transcriptome",
            "mode": "dense_only",
            "page": 1,
            "page_size": 20,
            "_evaluation_trace": True,
        }
    )

    trace = response["evaluation_trace"]
    assert trace["requested_mode"] == "dense_only"
    assert trace["effective_mode"] == "bm25_only"
    assert trace["components"]["dense"] == "failed"
    assert trace["components"]["lexical"] == "used"
    assert trace["configuration_sha256"] == effective_config
    assert trace["fallbacks"] == ["dense_failed:RuntimeError"]
