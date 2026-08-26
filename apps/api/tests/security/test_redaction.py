"""[T3] Log redaction — SENSITIVE_KEYS 가 어떤 stream 에도 평문으로 새지 않아야 한다.

ADR 0002 §CI Gates #2: 합성 마커 SECRETMARKER_<uuid> 를 검색 → 모든 로그에서 grep 0건.
"""
from __future__ import annotations

import io
import json
import re
import secrets

import pytest
import structlog

from src.security.policies import ALLOWED_SPAN_ATTRIBUTES, SENSITIVE_KEYS
from src.security.redaction import (
    REDACTED,
    configure_structlog,
    redact_processor,
    sanitize_span_attributes,
)

# ---------------------------------------------------------------------------
# 1. redact_processor — 직접 호출 테스트 (structlog 환경 무관)
# ---------------------------------------------------------------------------

def test_redact_top_level_sensitive_keys() -> None:
    event = {
        "event": "search",
        "query_text": "secret query",
        "query_id": "abc-123",  # not sensitive
        "result_count": 10,
    }
    out = redact_processor(None, "info", event)
    assert out["query_text"] == REDACTED
    assert out["query_id"] == "abc-123"
    assert out["result_count"] == 10


def test_redact_nested_dict() -> None:
    event = {
        "event": "test",
        "context": {
            "query_text": "leaked",
            "tenant_id": "t-1",  # not sensitive (logging-allowed)
        },
    }
    out = redact_processor(None, "info", event)
    assert out["context"]["query_text"] == REDACTED
    assert out["context"]["tenant_id"] == "t-1"


def test_redact_list_of_dicts() -> None:
    event = {
        "event": "batch",
        "items": [{"query_text": "a"}, {"query_text": "b"}, {"query_id": "x"}],
    }
    out = redact_processor(None, "info", event)
    assert all(item.get("query_text") == REDACTED for item in out["items"][:2])
    assert out["items"][2]["query_id"] == "x"


def test_all_sensitive_keys_recognized() -> None:
    """SENSITIVE_KEYS 의 모든 항목이 실제로 redact 된다."""
    for key in SENSITIVE_KEYS:
        marker = f"SHOULD_BE_REDACTED_{secrets.token_hex(4)}"
        out = redact_processor(None, "info", {"event": "x", key: marker})
        assert out[key] == REDACTED, f"{key} not redacted"


# ---------------------------------------------------------------------------
# 2. End-to-end — configure_structlog → JSON 출력에 SENSITIVE 가 없음
# ---------------------------------------------------------------------------

@pytest.fixture
def captured_log_stream(monkeypatch) -> io.StringIO:
    """structlog 의 PrintLoggerFactory 가 stderr 로 쓰므로, sys.stderr 를 StringIO 로 교체."""
    buf = io.StringIO()
    import sys

    monkeypatch.setattr(sys, "stderr", buf)
    configure_structlog(log_level="DEBUG", json_output=True)
    return buf


def test_log_redacts_query_text(captured_log_stream: io.StringIO) -> None:
    log = structlog.get_logger("test")
    marker = f"SECRETMARKER_{secrets.token_hex(8)}"
    log.info("user_search", query_text=marker, query_id="q-1", result_count=5)

    output = captured_log_stream.getvalue()
    assert marker not in output, f"SECRETMARKER leaked: {output!r}"
    assert REDACTED in output
    assert "q-1" in output  # non-sensitive 는 그대로


def test_log_redacts_inside_exception_context(captured_log_stream: io.StringIO) -> None:
    """exception path 에서도 query_text 가 redact 되어야 한다."""
    log = structlog.get_logger("test")
    marker = f"SECRETMARKER_{secrets.token_hex(8)}"
    try:
        raise ValueError("synthetic error")
    except ValueError:
        log.exception("query_failed", query_text=marker)

    output = captured_log_stream.getvalue()
    assert marker not in output
    assert REDACTED in output


def test_log_jsonrenderer_emits_valid_json(captured_log_stream: io.StringIO) -> None:
    """structlog 출력이 라인당 JSON 1건. 외부 ingestor (Loki 등) 와의 계약."""
    log = structlog.get_logger("test")
    log.info("event_a", k="v1")
    log.info("event_b", k="v2")
    lines = [ln for ln in captured_log_stream.getvalue().splitlines() if ln.strip()]
    assert len(lines) >= 2
    for ln in lines[-2:]:
        # 일부 라인에 ANSI 또는 prefix 가 없는지 — pure JSON 1줄이어야
        obj = json.loads(ln)
        assert "event" in obj
        assert "timestamp" in obj


# ---------------------------------------------------------------------------
# 3. OTel span sanitizer
# ---------------------------------------------------------------------------

def test_span_sanitizer_keeps_only_allowed() -> None:
    attrs = {
        "query_id": "q-1",
        "tenant_id": "t-1",
        "result_count": 7,
        "query_text": "should not appear",  # not in allowlist
        "random_attr": "neither this",
    }
    out = sanitize_span_attributes(attrs)
    assert "query_text" not in out
    assert "random_attr" not in out
    assert out["query_id"] == "q-1"
    assert out["tenant_id"] == "t-1"
    assert out["result_count"] == 7


def test_span_sanitizer_does_not_leak_sensitive() -> None:
    """SENSITIVE_KEYS 와 ALLOWED_SPAN_ATTRIBUTES 는 disjoint 여야 한다 — 정의 단계 invariant."""
    overlap = SENSITIVE_KEYS & ALLOWED_SPAN_ATTRIBUTES
    assert overlap == set(), (
        f"SENSITIVE_KEYS ↔ ALLOWED_SPAN_ATTRIBUTES overlap: {overlap}. "
        "이 둘이 겹치면 sanitize_span_attributes 가 sensitive 를 흘릴 수 있음."
    )


# ---------------------------------------------------------------------------
# 4. 합성 마커 grep — ADR 0002 §CI Gate #2 형태
# ---------------------------------------------------------------------------

def test_synthetic_marker_not_in_any_logged_field(captured_log_stream: io.StringIO) -> None:
    """일부러 다양한 SENSITIVE 슬롯에 동일 마커를 넣고, 출력에 어디에도 안 나타남을 검증."""
    log = structlog.get_logger("test")
    marker = f"SECRETMARKER_{secrets.token_hex(8)}"
    log.info(
        "ingest",
        query_text=marker,
        query_json={"q": marker},
        concept_terms=[{"term": marker}],
        result_count=3,
    )
    output = captured_log_stream.getvalue()
    assert re.search(re.escape(marker), output) is None, (
        f"marker {marker} leaked in: {output!r}"
    )
