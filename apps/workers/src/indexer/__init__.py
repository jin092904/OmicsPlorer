"""Indexer — harvester payload 를 datasets 테이블에 영속화.

각 source DB 별로 모듈 분리:
    - geo.py  GEO Series → datasets
    - (Week 2+) sra.py / ena.py / hca.py / gdc.py

Indexer 는 두 가지 layer:
    1. 순수 함수 (Celery 무관) — 본 패키지의 모듈들
    2. Celery 래퍼 — apps/workers/src/indexer/tasks.py

이렇게 분리해두면 unit test 와 ad-hoc 수확이 Celery 없이 돌아간다.
"""
