"""[T3] 보안 상수·정책 단일 출처.

structlog redact processor, OTel sanitizer, exception lint rule이 본 모듈을 import 한다.
이 집합을 변경하는 PR은 ADR 0002 갱신을 동반한다.
"""
from __future__ import annotations

# 로그·trace·예외 메시지에 절대 평문으로 노출되어선 안 되는 키
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "query_text",
    "query_json",
    "query_ciphertext",
    "concept_terms",
    "matched_concepts",
    "abstract_snippet",
    "saved_query_payload",
    "user_email",
    "clerk_session_token",
    "kms_dek",
    "kms_dek_ciphertext",
})

# OTel span attribute 화이트리스트 — 메타지표만 허용
ALLOWED_SPAN_ATTRIBUTES: frozenset[str] = frozenset({
    "query_id",
    "query_len",
    "query_sha256_prefix8",
    "tenant_id",
    "result_count",
    "candidate_count",
    "latency_ms",
    "model_version",
    "extraction_version",
})

# 보존 기간 (일) — ADR 0002 T5
RETENTION_DAYS_SEARCH_LOGS_DEFAULT = 30
RETENTION_DAYS_SEARCH_LOGS_MIN = 7
RETENTION_DAYS_SEARCH_FEEDBACK_RAW = 30  # 이후 집계 테이블로 대체

# 입력 sanitization 한도 — ADR 0002 T8
MAX_QUERY_LEN = 2000
