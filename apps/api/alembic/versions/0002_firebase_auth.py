"""firebase auth — users.clerk_id → firebase_uid + saved_datasets table.

ADR 0005 Firebase Auth 도입 후속:
- `users.clerk_id` 는 Clerk 시절 placeholder. Firebase uid 로 의미 변경 → 컬럼명 정규화.
- `users.display_name` 추가 — 토큰의 name claim 캐시.
- `saved_datasets` 추가 — localStorage 기반 찜을 서버 동기화. RLS FORCE.

Revision ID: 0002_firebase_auth
Revises: 0001_initial
Create Date: 2026-05-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_firebase_auth"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- users.clerk_id → users.firebase_uid -----------------------------
    op.alter_column("users", "clerk_id", new_column_name="firebase_uid")
    # 컬럼 rename 은 pg 가 인덱스/제약 이름을 자동 변경하지 않는다.
    op.execute("ALTER INDEX users_clerk_id_key RENAME TO users_firebase_uid_key")

    op.add_column("users", sa.Column("display_name", sa.Text, nullable=True))
    op.add_column("users", sa.Column("photo_url", sa.Text, nullable=True))

    # ---- saved_datasets --------------------------------------------------
    # 사용자가 결과에서 하트로 찜한 데이터셋. (dataset_id, user_id) UNIQUE.
    # ADR 0002 §12.3: tenant_id 필수 + RLS FORCE.
    op.create_table(
        "saved_datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "dataset_id", name="uq_saved_datasets_user_dataset"),
    )
    op.create_index("idx_saved_datasets_tenant", "saved_datasets", ["tenant_id"])
    op.create_index(
        "idx_saved_datasets_user_saved",
        "saved_datasets",
        ["user_id", sa.text("saved_at DESC")],
    )

    op.execute("ALTER TABLE saved_datasets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE saved_datasets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON saved_datasets
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """
    )

    # ---- app role 권한 ---------------------------------------------------
    # genofinder_app(NOSUPERUSER) 가 새 테이블에 접근할 수 있도록 GRANT.
    # 0001 의 postgres-init.sql 은 개별 테이블이 아닌 PUBLIC 스키마 GRANT 라
    # 새 테이블도 자동 적용되지만, ALTER DEFAULT PRIVILEGES 의존을 명시적으로 보강.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON saved_datasets TO genofinder_app")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade for 0002_firebase_auth is intentionally not supported. "
        "Restore from backup if rollback needed."
    )
