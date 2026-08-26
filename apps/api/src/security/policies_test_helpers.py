"""[T3] 합성 마커 — log redaction 테스트 (CI gate)에서 사용.

CI는 검색 요청에 SECRETMARKER_<uuid> 를 주입하고, 모든 로그 stream/file에서 grep해
검출되면 머지 차단한다 (ADR 0002 §CI Gates).
"""
from __future__ import annotations

import secrets

SECRET_MARKER_PREFIX = "SECRETMARKER_"  # pragma: allowlist secret


def make_test_marker() -> str:
    return f"{SECRET_MARKER_PREFIX}{secrets.token_hex(16)}"
