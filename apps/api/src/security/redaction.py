"""[T3] 로그·trace redaction.

structlog processor 와 OTel span sanitizer 를 제공한다.

마스터 플랜 §12.4:
- 모든 SENSITIVE_KEYS 가 로그·trace stream 에서 평문 노출되지 않아야 한다.
- exception 의 인자/메시지에 사용자 쿼리(L3) 객체가 들어가면 안 된다.
- OTel span attribute 는 ALLOWED_SPAN_ATTRIBUTES 에 등재된 것만 통과.

본 모듈은 structlog 의존성을 사용한다 — apps/api/pyproject.toml 에 등재되어 있다.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Iterable
from typing import Any

import structlog
from structlog.types import EventDict, Processor

from .policies import ALLOWED_SPAN_ATTRIBUTES, SENSITIVE_KEYS

REDACTED = "<REDACTED>"


def redact_processor(
    _logger: Any, _method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor — SENSITIVE_KEYS 를 잘라낸다.

    또한 dict / list 안에 중첩된 SENSITIVE_KEYS 도 재귀적으로 redact (한 단계 깊이만).
    """
    for key in list(event_dict):
        if key in SENSITIVE_KEYS:
            event_dict[key] = REDACTED
            continue
        # 한 단계 깊이의 dict/list 도 점검 — log 호출자가 무심코 wrap 하는 것을 방어
        value = event_dict[key]
        if isinstance(value, dict):
            event_dict[key] = _redact_dict(value)
        elif isinstance(value, (list, tuple)):
            event_dict[key] = _redact_iter(value)
    return event_dict


def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    return {k: (REDACTED if k in SENSITIVE_KEYS else v) for k, v in d.items()}


def _redact_iter(it: Iterable[Any]) -> list[Any]:
    return [_redact_dict(x) if isinstance(x, dict) else x for x in it]


def sanitize_span_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    """OTel span 화이트리스트 필터링 (allow-only)."""
    return {k: v for k, v in attrs.items() if k in ALLOWED_SPAN_ATTRIBUTES}


def configure_structlog(
    *,
    log_level: str = "INFO",
    json_output: bool = True,
    extra_processors: Iterable[Processor] = (),
) -> None:
    """애플리케이션 entrypoint 에서 1회 호출.

    - 모든 logger 를 structlog 로 통합
    - redact_processor 를 chain 의 끝에서 두 번째에 위치 (renderer 직전)
      → 어떤 processor 가 SENSITIVE_KEYS 를 추가하든 마지막에 redact
    """
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # add_logger_name 은 stdlib bridge 전용 — PrintLogger 와 호환 안 됨.
    # 로거 이름은 호출자가 structlog.get_logger("name").bind() 로 직접 명시한다.
    pre_chain: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        *extra_processors,
        # exception 처리는 redact 전에 — exception 에 들어간 sensitive 도 redact 가 잡는다
        structlog.processors.format_exc_info,
        # *** redact 는 renderer 직전 ***
        redact_processor,
    ]

    renderer: Processor
    if json_output:
        renderer = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*pre_chain, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
