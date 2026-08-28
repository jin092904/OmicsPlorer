"""Row-level metadata lineage identifiers used by current write paths.

Non-model harvest paths have stable identifiers because their transformation
is defined by source code. Model-assisted paths must receive an operator-frozen
identifier through the environment; a model tag or extraction-version label is
not enough to establish checkpoint, weights, prompt, and decoding provenance.
"""

from __future__ import annotations

import os
import re

GEO_STUB_LINEAGE_ID = "geo-esummary-stub-v0-2026-05-06"
SRA_STUB_LINEAGE_ID = "sra-esummary-stub-v0-2026-05-06"
HCA_SOURCE_LINEAGE_ID = "hca-azul-source-v2-2026-05-06"
GDC_SOURCE_LINEAGE_ID = "gdc-project-source-v2-2026-05-06"
DEMO_LINEAGE_ID = "synthetic-demo-non-model-v1"

BUILD_STAGE_SOURCE_STUB = "source_stub"
BUILD_STAGE_SOURCE_STRUCTURED = "source_structured"
BUILD_STAGE_ONTOLOGY_NORMALIZED = "ontology_normalized"
BUILD_STAGE_MODEL_STRUCTURED = "model_structured"
BUILD_STAGE_MODEL_ENRICHED = "model_enriched"

_SAFE_LINEAGE_RE = re.compile(r"[A-Za-z0-9_.-]+")


def configured_lineage_id(variable: str) -> str | None:
    """Return one explicit safe lineage ID, or ``None`` when not frozen."""

    value = os.environ.get(variable, "").strip()
    if not value:
        return None
    if not _SAFE_LINEAGE_RE.fullmatch(value):
        raise ValueError(f"{variable} must contain only A-Z, a-z, 0-9, dot, underscore, or hyphen")
    return value


def composite_lineage_id(stage_lineage_id: str | None, parent_lineage_id: str | None) -> str | None:
    """Bind one model stage to its known direct parent without inventing history."""

    if stage_lineage_id is None or parent_lineage_id is None:
        return None
    if not _SAFE_LINEAGE_RE.fullmatch(parent_lineage_id):
        return None
    return f"{stage_lineage_id}.after.{parent_lineage_id}"
