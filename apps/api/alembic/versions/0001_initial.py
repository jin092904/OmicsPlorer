"""initial — datasets/samples/publications + tenants/users + L3 encrypted + RLS

마스터 플랜 §4 (스키마) + §12.2 (envelope encryption) + §12.3 (multi-tenant RLS).

설계 메모:
- L0 (datasets, samples, dataset_publications, human_review_queue, extraction_failures):
  공개 metadata. tenant 개념 없음 — RLS 미적용.
- L2 (tenants, users, tenant_keys): tenant 자체. RLS 적용 (tenant 가 자신만 보도록).
- L3 (saved_queries, search_logs, search_feedback): 사용자 쿼리·클릭. envelope encrypt + RLS FORCE.

CRITICAL:
- saved_queries / search_logs 는 평문 query_json 컬럼을 만들지 않는다 (§12.2).
  대신 query_ciphertext BYTEA + query_aad JSONB.
- ENABLE + FORCE ROW LEVEL SECURITY — superuser 도 우회 못함.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- extensions ----
    # gen_random_uuid() 를 위해 pgcrypto 활성화. UUID 컬럼은 application 에서 생성하지 않고
    # DB default 로 발급 — race-free + KMS audit log 정합성.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # =====================================================================
    # L0 — Public metadata (NCBI/EBI 등 공개 카탈로그)
    # =====================================================================

    op.create_table(
        "datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_db", sa.Text, nullable=False),       # 'GEO' | 'SRA' | 'ENA' | 'HCA' | 'GDC' | ...
        sa.Column("source_id", sa.Text, nullable=False),       # 예: 'GSE176178'
        sa.Column("title", sa.Text),
        sa.Column("abstract", sa.Text),
        sa.Column("modality", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("organism_taxid", postgresql.ARRAY(sa.Integer), nullable=False, server_default="{}"),
        sa.Column("n_samples", sa.Integer),
        sa.Column("n_subjects", sa.Integer),
        sa.Column("n_subjects_confidence", sa.Float),
        sa.Column("n_conditions", sa.Integer),
        sa.Column("disease_ids", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("tissue_ids", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("cell_type_ids", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("assay_ids", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("access_type", sa.Text, nullable=False),     # 'open'|'controlled'|'embargoed'
        sa.Column("access_authority", sa.Text),
        sa.Column("license", sa.Text),
        sa.Column("has_processed_data", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("has_raw_data", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("metadata_completeness", sa.Float, nullable=False, server_default="0"),
        sa.Column("platform", sa.Text),
        sa.Column("library_strategy", sa.Text),
        sa.Column("submission_date", sa.Date),
        sa.Column("last_update", sa.Date),
        sa.Column("raw_metadata", postgresql.JSONB, nullable=False),
        sa.Column("extraction_version", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_db", "source_id", name="uq_datasets_source"),
        sa.CheckConstraint(
            "access_type IN ('open','controlled','embargoed')",
            name="ck_datasets_access_type",
        ),
    )
    op.create_index("idx_datasets_modality", "datasets", ["modality"], postgresql_using="gin")
    op.create_index("idx_datasets_disease", "datasets", ["disease_ids"], postgresql_using="gin")
    op.create_index("idx_datasets_tissue", "datasets", ["tissue_ids"], postgresql_using="gin")
    op.create_index("idx_datasets_access", "datasets", ["access_type"])
    op.create_index(
        "idx_datasets_submitted",
        "datasets",
        [sa.text("submission_date DESC")],
    )

    op.create_table(
        "samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_sample_id", sa.Text, nullable=False),
        sa.Column("subject_id", sa.Text),
        sa.Column("condition_label", sa.Text),
        sa.Column("raw_attributes", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint("dataset_id", "source_sample_id", name="uq_samples_source"),
    )
    op.create_index("idx_samples_dataset", "samples", ["dataset_id"])

    # 마스터 플랜 §4 의 PRIMARY KEY (dataset_id, COALESCE(pmid, doi)) 는 PG 가 직접 지원 안 함.
    # 대신 synthetic UUID PK + UNIQUE INDEX(expression) 로 치환.
    op.create_table(
        "dataset_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pmid", sa.Text),
        sa.Column("doi", sa.Text),
        sa.Column("citation_count", sa.Integer),
        sa.Column("journal", sa.Text),
        sa.Column("pub_year", sa.Integer),
        sa.CheckConstraint("pmid IS NOT NULL OR doi IS NOT NULL", name="ck_dp_ref"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_dp_dataset_ref "
        "ON dataset_publications (dataset_id, COALESCE(pmid, doi))"
    )

    # ---- LLM extraction failure queue (§5.2) ----
    op.create_table(
        "extraction_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_db", sa.Text, nullable=False),
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("extraction_version", sa.Text, nullable=False),
        sa.Column("error_class", sa.Text, nullable=False),
        sa.Column("error_message_hash", sa.Text, nullable=False),  # 평문 message 가 아닌 sha256 prefix (§12.4)
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_extraction_failures_src", "extraction_failures",
                    ["source_db", "source_id"])

    # ---- Low-confidence ontology mapping queue (§5.3) ----
    op.create_table(
        "human_review_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("term_text", sa.Text, nullable=False),
        sa.Column("ontology_namespace", sa.Text, nullable=False),  # MONDO|UBERON|CL|EFO
        sa.Column("candidate_id", sa.Text),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("reviewed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("reviewer_decision", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_review_queue_unreviewed", "human_review_queue",
                    ["reviewed"], postgresql_where=sa.text("NOT reviewed"))

    # =====================================================================
    # L2 — Tenants & users (RLS 적용)
    # =====================================================================

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("tier", sa.Text, nullable=False, server_default="free"),  # free|pro|lab
        sa.Column("retention_days_search_logs", sa.Integer, nullable=False, server_default="30"),  # §12.6
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("tier IN ('free','pro','lab')", name="ck_tenants_tier"),
    )

    # tenant 별 envelope DEK (§12.2 T1) — DEK 는 KEK(KMS) 로 wrap 된 형태로만 저장
    op.create_table(
        "tenant_keys",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("kek_kms_key_id", sa.Text, nullable=False),  # KMS key alias/ARN — Lab tier 의 CMK 도 동일 컬럼 (T6)
        sa.Column("dek_wrapped", postgresql.BYTEA, nullable=False),
        sa.Column("dek_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clerk_id", sa.Text, nullable=False, unique=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_users_tenant", "users", ["tenant_id"])

    # =====================================================================
    # L3 — Restricted (encrypted + RLS FORCE)
    # =====================================================================

    # saved_queries : 사용자 저장 쿼리. 평문 query_json 절대 만들지 않음.
    op.create_table(
        "saved_queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("query_ciphertext", postgresql.BYTEA, nullable=False),
        sa.Column("query_aad", postgresql.JSONB, nullable=False),
        sa.Column("dek_version", sa.Integer, nullable=False),
        sa.Column("alert_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_saved_queries_tenant", "saved_queries", ["tenant_id"])

    # search_logs : 호출 단위 로그. query 본문은 ciphertext 로만 저장.
    # 보존: 기본 30일 (§12.6) — 청소는 별도 Celery beat 에서.
    op.create_table(
        "search_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("query_ciphertext", postgresql.BYTEA, nullable=False),
        sa.Column("query_aad", postgresql.JSONB, nullable=False),
        sa.Column("dek_version", sa.Integer, nullable=False),
        sa.Column("result_count", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_search_logs_tenant", "search_logs", ["tenant_id"])
    op.create_index("idx_search_logs_created", "search_logs",
                    [sa.text("created_at DESC")])

    # search_feedback : 클릭/저장/평가 신호.
    # raw 보존 30일 후 집계 테이블로 회전 (§12.6) — 회전 작업은 별도 worker.
    op.create_table(
        "search_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("search_log_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("search_logs.id", ondelete="CASCADE")),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("datasets.id", ondelete="SET NULL")),
        sa.Column("rank", sa.Integer),
        sa.Column("signal", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "signal IN ('click','save','export','thumbs_up','thumbs_down','irrelevant')",
            name="ck_feedback_signal",
        ),
    )
    op.create_index("idx_feedback_tenant", "search_feedback", ["tenant_id"])

    # =====================================================================
    # RLS — §12.3 T4
    # =====================================================================
    # tenant_keys 까지 포함해 모든 L2/L3 테이블에 적용.
    # NOTE: ENABLE + FORCE — superuser 도 정책을 준수해야 한다 (단, BYPASSRLS 권한이 있는 role 은 우회 가능).
    #       마이그레이션 자체는 본 트랜잭션 내에서 owner 권한으로 실행되므로 정책에 막히지 않는다.

    rls_tables = [
        "tenants",
        "tenant_keys",
        "users",
        "saved_queries",
        "search_logs",
        "search_feedback",
    ]
    for tbl in rls_tables:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY")

    # tenants 테이블의 self-row 정책 — id = current_tenant
    op.execute("""
        CREATE POLICY tenant_self ON tenants
          USING (id = current_setting('app.tenant_id', true)::uuid)
    """)

    # 그 외 테이블은 tenant_id = current_tenant
    for tbl in ["tenant_keys", "users", "saved_queries", "search_logs", "search_feedback"]:
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {tbl}
              USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
              WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)


def downgrade() -> None:
    # downgrade 는 v1 에서 미지원 (data loss 위험). 의도적으로 비워둔다.
    raise RuntimeError(
        "Downgrade for 0001_initial is intentionally not supported. "
        "Restore from backup if rollback needed."
    )
