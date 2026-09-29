from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.indexer.embeddings import _payload
from src.indexer.lexical import (
    INDEX_BODY,
    INDEX_NAME,
    LexicalIndexMappingError,
    _doc,
    ensure_index,
    recreate_index,
)


def _row() -> dict:
    return {
        "id": "6bb4f9fa-c0e0-4b7e-80d5-b5f0df6f19fe",
        "source_db": "GEO",
        "source_id": "GSE1",
        "title": "Example",
        "abstract": "Example abstract",
        "access_type": "open",
        "submission_date": date(2026, 1, 1),
        "extraction_version": "v1",
        "extraction_lineage_id": "model-v1.after.source-v1",
        "build_stage": "model_structured",
    }


def test_qdrant_payload_retains_row_lineage() -> None:
    payload = _payload(_row())

    assert payload["extraction_version"] == "v1"
    assert payload["extraction_lineage_id"] == "model-v1.after.source-v1"
    assert payload["build_stage"] == "model_structured"


def test_opensearch_document_and_mapping_retain_row_lineage() -> None:
    document = _doc(_row())
    properties = INDEX_BODY["mappings"]["properties"]

    assert document["extraction_lineage_id"] == "model-v1.after.source-v1"
    assert document["build_stage"] == "model_structured"
    assert properties["extraction_lineage_id"] == {"type": "keyword"}
    assert properties["build_stage"] == {"type": "keyword"}


async def test_existing_opensearch_index_receives_missing_lineage_mapping() -> None:
    indices = SimpleNamespace(
        exists=AsyncMock(return_value=True),
        get_mapping=AsyncMock(
            return_value={INDEX_NAME: {"mappings": {"properties": {"dataset_id": {}}}}}
        ),
        put_mapping=AsyncMock(),
    )
    client = SimpleNamespace(indices=indices)

    await ensure_index(client)

    indices.put_mapping.assert_awaited_once_with(
        index=INDEX_NAME,
        body={
            "properties": {
                "extraction_lineage_id": {"type": "keyword"},
                "build_stage": {"type": "keyword"},
            }
        },
    )


async def test_existing_index_with_text_mapped_filter_fields_is_rejected() -> None:
    # Dynamic mapping stores strings as analyzed text, where term filters match nothing.
    text_field = {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}}
    indices = SimpleNamespace(
        exists=AsyncMock(return_value=True),
        get_mapping=AsyncMock(
            return_value={INDEX_NAME: {"mappings": {"properties": {
                "source_db": text_field,
                "disease_ids": text_field,
                "title": {"type": "text"},
            }}}}
        ),
        put_mapping=AsyncMock(),
    )
    client = SimpleNamespace(indices=indices)

    with pytest.raises(LexicalIndexMappingError, match="disease_ids=text, source_db=text"):
        await ensure_index(client)
    indices.put_mapping.assert_not_awaited()


async def test_recreate_index_replaces_existing_index_with_expected_mapping() -> None:
    indices = SimpleNamespace(
        exists=AsyncMock(return_value=True),
        delete=AsyncMock(),
        create=AsyncMock(),
    )
    client = SimpleNamespace(indices=indices)

    await recreate_index(client)

    indices.delete.assert_awaited_once_with(index=INDEX_NAME)
    indices.create.assert_awaited_once_with(index=INDEX_NAME, body=INDEX_BODY)
