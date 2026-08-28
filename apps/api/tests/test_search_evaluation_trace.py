"""Fail-closed execution-trace tests for frozen retrieval evaluation."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from src.services import search as search_service


class _FakeQdrant:
    def __init__(self, **_: Any) -> None:
        pass

    async def query_points(self, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(
            points=[
                SimpleNamespace(
                    id="00000000-0000-0000-0000-000000000001",
                    score=0.8,
                    payload={
                        "source_db": "GEO",
                        "source_id": "GSE1",
                        "title": "synthetic test record",
                        "organism_taxid": [9606],
                        "access_type": "open",
                    },
                )
            ]
        )

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
    monkeypatch.setenv("OLLAMA_MODEL_EMBED", "test-embedding")
    monkeypatch.setenv("OLLAMA_MODEL_EXTRACTION", "test-translation")
    monkeypatch.setenv("RERANKER_MODEL", "test-reranker")
    monkeypatch.setenv("RERANKER_TOP_N", "20")
    configuration = {
        "schema_version": "omicsplorer-effective-server-config-v1",
        "corpus": "production",
        "lexical_index": "datasets_v2",
        "dense_collection": "datasets_v2",
        "lexical_candidate_count": 200,
        "dense_candidate_count": 200,
        "rrf_k": 60,
        "query_embedding": {
            "checkpoint": "test-embedding",
            "truncation_dimension": 1024,
        },
        "reranker": {"checkpoint": "test-reranker", "top_n": 20},
        "translation": {
            "enabled": True,
            "model": {"checkpoint": "test-translation"},
        },
        "query_understanding": {"enabled": False, "model": None},
        "access_preference": "open_only",
        "accession_shortcut_enabled": True,
        "cardinality_boost_enabled": True,
    }
    path = tmp_path / "effective-server-config.json"
    path.write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setenv("EFFECTIVE_SERVER_CONFIG_PATH", str(path))
    search_service._canonical_json_file.cache_clear()
    canonical = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


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


def test_runtime_configuration_mismatch_invalidates_trace() -> None:
    trace = search_service._EvaluationTraceState(
        enabled=True,
        requested_mode="rrf",
    )
    search_service._record_configuration_mismatches(
        trace,
        {"rrf_k": 61, "reranker": {"top_n": 20}},
        {"rrf_k": 60, "reranker.top_n": 20},
    )
    assert trace.fallbacks == ["configuration_runtime_mismatch:rrf_k"]


def test_missing_configuration_invalidates_trace() -> None:
    trace = search_service._EvaluationTraceState(
        enabled=True,
        requested_mode="rrf",
    )
    search_service._record_configuration_mismatches(trace, None, {"rrf_k": 60})
    assert trace.fallbacks == ["configuration_missing_or_invalid"]


@pytest.mark.parametrize(
    ("mode", "expected_components"),
    [
        ("bm25_only", ("used", "not_requested", "not_requested")),
        ("dense_only", ("not_requested", "used", "not_requested")),
        ("rrf", ("used", "used", "not_requested")),
        ("rrf_rerank", ("used", "used", "used")),
    ],
)
async def test_each_requested_mode_records_its_complete_effective_path(
    mode: str,
    expected_components: tuple[str, str, str],
    effective_config: str,
    monkeypatch,
) -> None:
    async def fake_embedding(_: str) -> list[float]:
        return [0.0] * 1024

    import src.services.reranker as reranker_service

    monkeypatch.setattr(search_service, "AsyncQdrantClient", _FakeQdrant)
    monkeypatch.setattr(search_service, "AsyncOpenSearch", _FakeOpenSearch)
    monkeypatch.setattr(search_service, "_embed_query", fake_embedding)
    monkeypatch.setattr(reranker_service, "is_available", lambda: True)
    monkeypatch.setattr(reranker_service, "rerank_top_n", lambda: 20)
    monkeypatch.setattr(
        reranker_service,
        "rerank_pairs",
        lambda _query, docs: [1.25] * len(docs),
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("QUERY_UNDERSTANDING_ENABLED", "0")

    response = await search_service.hybrid_search(
        {
            "query_text": "human transcriptome",
            "mode": mode,
            "page": 1,
            "page_size": 20,
            "auto_translate": True,
            "_evaluation_trace": True,
        }
    )

    trace = response["evaluation_trace"]
    assert trace["requested_mode"] == mode
    assert trace["effective_mode"] == mode
    assert trace["configuration_sha256"] == effective_config
    assert trace["fallbacks"] == []
    assert (
        trace["components"]["lexical"],
        trace["components"]["dense"],
        trace["components"]["reranker"],
    ) == expected_components


async def test_korean_query_records_successful_translation(
    effective_config: str,
    monkeypatch,
) -> None:
    async def fake_translation(_: str, *, target_lang: str) -> str:
        assert target_lang == "en"
        return "human lung transcriptome"

    import src.services.translate as translate_service

    monkeypatch.setattr(search_service, "AsyncQdrantClient", _FakeQdrant)
    monkeypatch.setattr(search_service, "AsyncOpenSearch", _FakeOpenSearch)
    monkeypatch.setattr(translate_service, "translate_query", fake_translation)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("QUERY_UNDERSTANDING_ENABLED", "0")

    response = await search_service.hybrid_search(
        {
            "query_text": "사람 폐 전사체",
            "mode": "bm25_only",
            "page": 1,
            "page_size": 20,
            "auto_translate": True,
            "_evaluation_trace": True,
        }
    )

    assert response["original_query"] == "사람 폐 전사체"
    assert response["translated_query"] == "human lung transcriptome"
    trace = response["evaluation_trace"]
    assert trace["components"]["translation"] == "used"
    assert trace["configuration_sha256"] == effective_config
    assert trace["fallbacks"] == []


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
