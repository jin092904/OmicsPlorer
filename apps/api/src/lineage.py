"""Fail-closed helpers for API-side metadata lineage writes."""

from __future__ import annotations

import os
import re

BUILD_STAGE_MODEL_ENRICHED = "model_enriched"
_SAFE_LINEAGE_RE = re.compile(r"[A-Za-z0-9_.-]+")


def configured_lineage_id(variable: str) -> str | None:
    value = os.environ.get(variable, "").strip()
    if not value:
        return None
    if not _SAFE_LINEAGE_RE.fullmatch(value):
        raise ValueError(f"{variable} contains an unsafe lineage identifier")
    return value


def composite_lineage_id(stage_lineage_id: str | None, parent_lineage_id: str | None) -> str | None:
    if stage_lineage_id is None or parent_lineage_id is None:
        return None
    if not _SAFE_LINEAGE_RE.fullmatch(parent_lineage_id):
        return None
    return f"{stage_lineage_id}.after.{parent_lineage_id}"
