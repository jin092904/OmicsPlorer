"""Reranker — 마스터 플랜 §6.1 Step 6.

RRF 머지 후 top-N 에 reranker 를 적용해 정밀도를 높인다.

v0 (deprecated): `cross-encoder/ms-marco-MiniLM-L-6-v2` (≈80 MB, 영어 only, 5년 됨)
**v2 (ADR 0006)**: `Qwen/Qwen3-Reranker-0.6B` (568M, multilingual 한국어 강함, Apache 2.0, BGE-v2 대비 +12.7점 MTEB-R)

sentence-transformers `CrossEncoder` 인터페이스 그대로 — Qwen3-Reranker 도 `model.predict([(query, doc), ...])` 호환.

설계:
- 모델은 lazy load — 첫 /search 호출에서 ~수 초 부하, 이후 메모리 상주.
- 모델 로딩 실패 시 (메모리/네트워크) None 반환 → 호출자는 RRF 점수만 사용 (graceful degradation).
- 사용자 쿼리는 ephemeral — 모델 입력으로만 사용 후 폐기 (ADR 0002 T7).
- GPU 가용 시 자동 사용 (sentence-transformers 가 cuda.is_available() 으로 결정).
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ADR 0006: Qwen3-Reranker-0.6B 으로 교체. ms-marco-MiniLM-L-6-v2 는 deprecated.
DEFAULT_MODEL = "Qwen/Qwen3-Reranker-0.6B"
# 평가 기록과 같은 가중치를 받도록 DEFAULT_MODEL 의 Hugging Face revision 을 고정.
# DEFAULT_MODEL 에만 적용. 바꾸려면 RERANKER_REVISION (예: "main").
DEFAULT_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
# Qwen3-Reranker-0.6B GPU 기준 ~50ms/pair, CPU ~500ms/pair.
# top_n 은 RRF 머지 결과의 상위 N개를 rerank. 정확도 vs latency 트레이드오프.
DEFAULT_TOP_K = 20

_model: Any = None  # CrossEncoder instance — lazy
_model_lock = threading.Lock()
_model_disabled = False  # 로딩 실패 시 retry 폭주 방지


def _get_model() -> Any | None:
    """Lazy singleton. import 실패 / 로드 실패 시 None — graceful degradation.

    RERANKER_TOP_N <= 0 일 때 None — 모델 로드 자체를 시도 안 함.
    """
    global _model, _model_disabled
    if rerank_top_n() <= 0:
        return None
    if _model is not None or _model_disabled:
        return _model
    with _model_lock:
        if _model is not None or _model_disabled:
            return _model
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
        except ImportError as e:
            logger.warning("sentence-transformers not installed: %s — reranker disabled", e)
            _model_disabled = True
            return None
        name, revision = configured_model()
        try:
            _model = CrossEncoder(name, revision=revision) if revision else CrossEncoder(name)
            logger.info("loaded cross-encoder %s (revision=%s)", name, revision or "default")
        except Exception as e:
            logger.warning("CrossEncoder load failed (%s): %s — reranker disabled", name, e)
            _model_disabled = True
            return None
        return _model


def configured_model() -> tuple[str, str | None]:
    """Model name and Hugging Face revision that ``_get_model`` loads."""
    name = os.environ.get("RERANKER_MODEL") or DEFAULT_MODEL
    revision = os.environ.get("RERANKER_REVISION") or (
        DEFAULT_REVISION if name == DEFAULT_MODEL else None
    )
    return name, revision


def is_available() -> bool:
    return _get_model() is not None


def rerank_pairs(query: str, docs: list[str]) -> list[float] | None:
    """반환: docs 와 같은 길이의 score 리스트 (정렬되지 않음). None = 모델 미가용.

    호출자는 score 와 hit 을 zip 하여 정렬.
    """
    model = _get_model()
    if model is None or not docs:
        return None
    pairs = [(query, d) for d in docs]
    try:
        # CrossEncoder.predict 는 sync — 호출자가 thread-pool 또는 짧은 호출이면 직접.
        scores = model.predict(pairs, show_progress_bar=False)
    except Exception as e:
        logger.warning("rerank predict failed: %s", e)
        return None
    return [float(s) for s in scores]


def rerank_top_n() -> int:
    val = os.environ.get("RERANKER_TOP_N")
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return DEFAULT_TOP_K


def main() -> int:
    """모델을 받아 한 번 로드하고 한 쌍을 채점. Compose 의 model-pull-reranker 가 실행."""
    logging.basicConfig(level=logging.INFO)
    name, revision = configured_model()
    scores = rerank_pairs("single-cell RNA-seq", ["single-cell RNA sequencing of mouse brain"])
    if scores is None:
        print(f"reranker unavailable: {name} (revision={revision or 'default'})", file=sys.stderr)
        return 1
    print(f"reranker ready: {name} (revision={revision or 'default'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
