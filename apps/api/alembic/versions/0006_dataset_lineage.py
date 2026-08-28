"""datasets row-level extraction lineage and build stage.

The new columns are intentionally nullable. Existing production rows were
created by mixed historical paths and cannot be assigned a verified lineage
from ``extraction_version`` alone. A frozen release must either reprocess them
under a recorded lineage or supply separate evidence before filling them.

Revision ID: 0006_dataset_lineage
Revises: 0005_dataset_sources
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_dataset_lineage"
down_revision = "0005_dataset_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("extraction_lineage_id", sa.Text, nullable=True),
    )
    op.add_column(
        "datasets",
        sa.Column("build_stage", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_datasets_extraction_lineage",
        "datasets",
        ["extraction_lineage_id"],
    )
    op.create_index("idx_datasets_build_stage", "datasets", ["build_stage"])


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade for 0006_dataset_lineage is intentionally not supported."
    )
