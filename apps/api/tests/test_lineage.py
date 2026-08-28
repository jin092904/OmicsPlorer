from __future__ import annotations

import pytest

from src.lineage import composite_lineage_id, configured_lineage_id


def test_api_lineage_is_unset_by_default(monkeypatch) -> None:
    monkeypatch.delenv("COHORT_EXTRACTION_LINEAGE_ID", raising=False)

    assert configured_lineage_id("COHORT_EXTRACTION_LINEAGE_ID") is None


def test_api_lineage_rejects_unsafe_identifier(monkeypatch) -> None:
    monkeypatch.setenv("COHORT_EXTRACTION_LINEAGE_ID", "cohort/model")

    with pytest.raises(ValueError, match="unsafe"):
        configured_lineage_id("COHORT_EXTRACTION_LINEAGE_ID")


def test_api_composite_lineage_fails_closed_without_parent() -> None:
    assert composite_lineage_id("cohort-v2", "source-v1") == "cohort-v2.after.source-v1"
    assert composite_lineage_id("cohort-v2", None) is None
