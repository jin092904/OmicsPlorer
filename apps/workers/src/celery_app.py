"""Celery app — broker/backend 는 Redis (compose service 'redis').

본 모듈은 task discovery 의 단일 진입점이며 beat 스케줄도 정의한다.

ADR 0002 T3: 본 app 의 logging 은 redaction processor 가 적용된 structlog 로 통합되어야 한다.
현재는 placeholder — 실제 구성은 보안 모듈 구현 PR (Week 7) 에서.

Beat 스케줄 (UTC 기준):
- 02:00 GEO incremental
- 02:30 HCA incremental
- 03:00 GDC incremental
- 03:30 ENA mirror backfill (신규 SRA → ENA mirror 1:1 자동 propagate, idempotent)
- 04:00 reindex_all (전체 다시 임베딩 + Qdrant + OS)

각 source 별 incremental 은 watermark 기반 (마지막 성공 시각 이후 갱신된 records).
ENA backfill 은 dataset_sources 전체 NOT EXISTS 기반 idempotent INSERT — watermark 불필요.
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

app = Celery(
    "genofinder_workers",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "src.indexer.tasks",
    ],
)

app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=30,
    worker_prefetch_multiplier=1,  # heavy task 라 1개씩만
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
)

app.conf.beat_schedule = {
    "harvest-geo-daily": {
        "task": "src.indexer.tasks.harvest_geo_incremental",
        "schedule": crontab(hour=2, minute=0),
    },
    "harvest-hca-daily": {
        "task": "src.indexer.tasks.harvest_hca_incremental",
        "schedule": crontab(hour=2, minute=30),
    },
    "harvest-gdc-daily": {
        "task": "src.indexer.tasks.harvest_gdc_incremental",
        "schedule": crontab(hour=3, minute=0),
    },
    "backfill-ena-mirror-daily": {
        "task": "src.indexer.tasks.backfill_ena_mirror",
        "schedule": crontab(hour=3, minute=30),
    },
    "reindex-nightly": {
        "task": "src.indexer.tasks.reindex_all",
        "schedule": crontab(hour=4, minute=0),
    },
    # ─── self-healing 점진 재태깅 (2026-06-12 준비, 아직 비활성) ────────────────
    # 활성화 절차 (1회성 Sol4 런 완료 후):
    #   1) 아래 블록 주석 해제 → celery beat 재시작 (systemctl --user restart genofinder-celery-beat)
    #   2) 도입 첫 3-5일은 shadow 기본(SOL4_AUTO_COMMIT 미설정) → 로그에서 SHADOW diff 검토
    #   3) diff 가 안전하다 판단되면 worker 환경에 SOL4_AUTO_COMMIT=1 추가 후 worker 재시작 → 실제 write
    # 21:00 UTC = 06:00 KST. 기존 하베스트/reindex 창(02-05 UTC)과 분리 → GPU 경합 0.
    # "retag-tissue-daily": {
    #     "task": "src.indexer.tasks.retag_tissue_daily",
    #     "schedule": crontab(hour=21, minute=0),
    # },
}
