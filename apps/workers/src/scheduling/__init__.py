"""Celery beat scheduler — 정기 source 갱신.

Watermark (마지막 성공 실행 시각) 은 Redis 에 저장:
    `gf:source_run:<SOURCE_DB>:last_run_at` → ISO 문자열

동일 source 의 task 가 동시 실행되지 않게 lock:
    `gf:source_lock:<SOURCE_DB>` → SET NX EX <ttl>
"""
