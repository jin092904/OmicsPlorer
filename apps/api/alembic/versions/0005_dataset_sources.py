"""dataset_sources + bioproject_id — Phase 1 of SRA/ENA integration

목적:
- 한 study(dataset row) 에 여러 source ref (GEO + SRA + ENA + …) 를 1:N 으로 연결.
- BioProject ID(PRJNA…) 를 canonical pivot 으로 활용 — INSDC 공동 키.

설계 메모:
- datasets.bioproject_id 는 nullable Text — 모든 source 에 BioProject 있는 건 아님(예: array).
  Phase 1 backfill 에서 GEO raw_metadata 의 'bioproject' 값으로 채움.
- dataset_sources 는 L0(Public) — RLS 미적용.
- (dataset_id, source_db, source_id) 가 PK — 같은 dataset 에 같은 (source_db, source_id) 중복 방지.
- linked_via: 'original'(primary harvest) | 'extrelations'(GEO raw_metadata 의 SRA cross-ref) |
  'elink'(NCBI EUtils, 미래) | 'manual'.
- is_primary: dataset 표시용 우선 source. 보통 GEO > GDC > SRA > ENA 순.

Revision ID: 0005_dataset_sources
Revises: 0004_samples_cohort
Create Date: 2026-05-27
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_dataset_sources"
down_revision = "0004_samples_cohort"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("datasets", sa.Column("bioproject_id", sa.Text, nullable=True))
    op.create_index("idx_datasets_bioproject", "datasets", ["bioproject_id"])

    op.create_table(
        "dataset_sources",
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_db", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("raw_url", sa.Text),
        sa.Column(
            "is_primary", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "linked_via",
            sa.Text,
            nullable=False,
            server_default=sa.text("'original'::text"),
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint(
            "dataset_id", "source_db", "source_id", name="pk_dataset_sources"
        ),
    )
    op.create_index(
        "idx_dataset_sources_lookup",
        "dataset_sources",
        ["source_db", "source_id"],
    )
    op.create_index(
        "idx_dataset_sources_dataset", "dataset_sources", ["dataset_id"]
    )

    # app role(NOSUPERUSER) 가 읽을 수 있어야 함 — L0 public.
    op.execute("GRANT SELECT ON dataset_sources TO genofinder_app")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON dataset_sources FROM genofinder_app")
    op.drop_index("idx_dataset_sources_dataset", table_name="dataset_sources")
    op.drop_index("idx_dataset_sources_lookup", table_name="dataset_sources")
    op.drop_table("dataset_sources")
    op.drop_index("idx_datasets_bioproject", table_name="datasets")
    op.drop_column("datasets", "bioproject_id")
