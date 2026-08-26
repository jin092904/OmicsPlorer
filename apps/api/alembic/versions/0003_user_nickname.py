"""users.nickname — 커뮤니티 노출용 별명.

display_name 은 Firebase 토큰의 displayName 을 그대로 캐시하지만,
커뮤니티에서 노출되는 이름은 사용자가 직접 정할 수 있어야 한다.

Revision ID: 0003_user_nickname
Revises: 0002_firebase_auth
Create Date: 2026-05-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_user_nickname"
down_revision: str | Sequence[str] | None = "0002_firebase_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.Text, nullable=True))
    # 초기 값은 NULL — UI 가 fallback 으로 display_name 또는 email local-part 을 보여준다.


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade for 0003_user_nickname is intentionally not supported."
    )
