from __future__ import annotations

import pytest

from src.lineage import composite_lineage_id, configured_lineage_id


def test_configured_lineage_requires_explicit_environment(monkeypatch) -> None:
    monkeypatch.delenv("METADATA_EXTRACTION_LINEAGE_ID", raising=False)

    assert configured_lineage_id("METADATA_EXTRACTION_LINEAGE_ID") is None


def test_configured_lineage_rejects_unsafe_value(monkeypatch) -> None:
    monkeypatch.setenv("METADATA_EXTRACTION_LINEAGE_ID", "model/v1")

    with pytest.raises(ValueError, match="must contain only"):
        configured_lineage_id("METADATA_EXTRACTION_LINEAGE_ID")


def test_composite_lineage_requires_both_verified_stages() -> None:
    assert composite_lineage_id("model-v2", "source-v1") == "model-v2.after.source-v1"
    assert composite_lineage_id(None, "source-v1") is None
    assert composite_lineage_id("model-v2", None) is None
    assert composite_lineage_id("model-v2", "unsafe/parent") is None
