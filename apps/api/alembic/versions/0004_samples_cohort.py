"""samples 확장 (sex/age/condition) + datasets.cohort_design JSONB

목적:
- 데이터셋 상세 페이지의 코호트 분포 시각화(성비·연령·condition 라벨)
- 실험군/대조군 도식화 (LLM 으로 추출한 그룹 구조)

설계 메모:
- samples 테이블은 L0(Public) — RLS 미적용 유지.
- sex/age_value/age_unit/disease_state/treatment 모두 nullable — Series Matrix 의
  Sample_characteristics_ch1 는 source 마다 키 이름이 다르고 일부 필드만 채워질 수 있다.
- sex 는 'male' | 'female' | 'unknown' (canonical, lowercase) — 입력 다양성(M/F, Male/Female,
  남/여 등)을 indexer 가 정규화한다. CHECK 제약은 두지 않음 (저장 시점에 외부 데이터의
  새 표기를 받아들이고, 시각화 단계에서 unknown 으로 fallback).
- age_value 는 FLOAT — '23.5' / '18-25 (mid 21.5)' 같은 케이스 모두 표현 가능.
  age_unit 는 'year' / 'month' / 'day' (canonical lower).
- disease_state / treatment 는 free text — 라벨 분포 시각화용.
- datasets.cohort_design 은 JSONB — schema 는 cohort_design extractor 가 강제 (extraction
  version 으로 호환성 관리). 컬럼은 nullable — 추출 안 된 데이터셋은 NULL.

Revision ID: 0004_samples_cohort
Revises: 0003_user_nickname
Create Date: 2026-05-12
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_samples_cohort"
down_revision: str | Sequence[str] | None = "0003_user_nickname"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---- samples 확장 ----
    op.add_column("samples", sa.Column("sex", sa.Text, nullable=True))
    op.add_column("samples", sa.Column("age_value", sa.Float, nullable=True))
    op.add_column("samples", sa.Column("age_unit", sa.Text, nullable=True))
    op.add_column("samples", sa.Column("disease_state", sa.Text, nullable=True))
    op.add_column("samples", sa.Column("treatment", sa.Text, nullable=True))

    # 시각화 쿼리(`SELECT sex, count(*) GROUP BY sex` 등)는 dataset_id 로 먼저 필터되므로
    # idx_samples_dataset (0001) 이면 충분. 추가 인덱스 생략.

    # ---- datasets.cohort_design ----
    op.add_column(
        "datasets",
        sa.Column("cohort_design", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "datasets",
        sa.Column("cohort_design_version", sa.Text, nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade for 0004_samples_cohort is intentionally not supported."
    )
