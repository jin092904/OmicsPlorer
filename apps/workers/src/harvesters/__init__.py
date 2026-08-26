"""Harvester registry.

각 source 별 harvester 는 Harvester ABC 를 상속한다 (base.py).
신규 source 추가 시:
    1. docs/external-apis.md 에 base URL/auth/rate limit 등재
    2. 본 디렉토리에 <source>.py 추가
    3. apps/workers/src/celery_app.py 의 task registry 갱신
"""
