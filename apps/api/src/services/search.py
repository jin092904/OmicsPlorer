"""Hybrid search — Qdrant (semantic) + OpenSearch (BM25), RRF merge.

마스터 플랜 §6.1 의 v0 단순화:
    - 양쪽에서 top K 가져와 Reciprocal Rank Fusion 으로 합친다.
    - Cross-encoder rerank·랭킹 점수 함수는 Week 7+ (별도 service 모듈).

ADR 0003 T7: 사용자 쿼리 임베딩은 ephemeral — Qdrant 에 저장하지 않는다.
본 모듈은 query 시점에만 임베딩을 만들고, 결과 반환 후 메모리에서 사라진다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from opensearchpy._async.client import AsyncOpenSearch
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

logger = logging.getLogger(__name__)

# ADR 0006: v2 = Qwen3-Embedding 1024d. v1 (768d nomic) deprecated.
QDRANT_COLLECTION = "datasets_v2"
OS_INDEX = "datasets_v2"

# Evaluation 용 corpus switch — production 외에 bioCADDIE OOD generalization 평가.
EVAL_CORPUS_QDRANT = {
    "production": QDRANT_COLLECTION,
    "biocaddie_2016_eval": "biocaddie_2016_eval",
}
EVAL_CORPUS_OS = {
    "production": OS_INDEX,
    "biocaddie_2016_eval": "biocaddie_2016_eval",
}

DEFAULT_OLLAMA_URL = "http://ollama:11434"
DEFAULT_QDRANT_URL = "http://qdrant:6333"
DEFAULT_OS_URL = "http://opensearch:9200"
RRF_K = 60  # 일반적인 RRF 상수
MIN_top_k = 50
MAX_top_k = 200  # 페이지 ≥ 10 까지 안전한 상한


@dataclass
class HybridHit:
    dataset_id: str
    payload: dict[str, Any]
    semantic: float | None = None
    lexical: float | None = None
    semantic_rank: int | None = None
    lexical_rank: int | None = None
    rrf: float = 0.0
    rerank: float | None = None


_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _env_enabled(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _ENABLED_VALUES


@lru_cache(maxsize=4)
def _canonical_json_file_sha256(path_text: str) -> str:
    """Hash parsed JSON using the frozen-release canonicalization contract."""

    raw = json.loads(Path(path_text).read_text(encoding="utf-8"))
    canonical = json.dumps(
        raw,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _effective_configuration_sha256() -> str | None:
    """Return the digest of the mounted effective-server configuration.

    A caller cannot supply a digest directly: the API computes it from the
    parsed JSON file that is mounted into the evaluated deployment. Missing or
    invalid evidence produces ``None`` and is rejected by the offline release
    validator without affecting ordinary product requests.
    """

    path_text = os.environ.get("EFFECTIVE_SERVER_CONFIG_PATH", "").strip()
    if not path_text:
        return None
    try:
        return _canonical_json_file_sha256(path_text)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(
            "effective server configuration unavailable (%s)",
            type(exc).__name__,
        )
        return None


@dataclass
class _EvaluationTraceState:
    """Mutable internal execution state converted to the public trace at return."""

    enabled: bool
    requested_mode: str
    configuration_sha256: str | None = None
    lexical: str = "not_requested"
    dense: str = "not_requested"
    reranker: str = "not_requested"
    translation: str = "not_needed"
    query_understanding: str = "disabled"
    accession_shortcut_enabled: bool = True
    accession_shortcut_applied: bool = False
    cardinality_boost_enabled: bool = True
    cardinality_boost_applied: bool = False
    fallbacks: list[str] = field(default_factory=list)

    def effective_mode(self) -> str:
        lexical_used = self.lexical == "used"
        dense_used = self.dense == "used"
        reranker_used = self.reranker == "used"
        if lexical_used and dense_used:
            return "rrf_rerank" if reranker_used else "rrf"
        if lexical_used:
            return "bm25_rerank" if reranker_used else "bm25_only"
        if dense_used:
            return "dense_rerank" if reranker_used else "dense_only"
        return "unavailable"

    def as_dict(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        return {
            "requested_mode": self.requested_mode,
            "effective_mode": self.effective_mode(),
            "configuration_sha256": self.configuration_sha256,
            "components": {
                "lexical": self.lexical,
                "dense": self.dense,
                "reranker": self.reranker,
                "translation": self.translation,
                "query_understanding": self.query_understanding,
                "accession_shortcut": {
                    "enabled": self.accession_shortcut_enabled,
                    "applied": self.accession_shortcut_applied,
                },
                "cardinality_boost": {
                    "enabled": self.cardinality_boost_enabled,
                    "applied": self.cardinality_boost_applied,
                },
            },
            "fallbacks": list(self.fallbacks),
        }


_ARRAY_FIELDS = (
    ("modality", "modality"),
    ("organism_taxid", "organism_taxid"),
    ("library_strategy", "library_strategy"),
    ("disease_ids", "disease_ids"),
    ("tissue_ids", "tissue_ids"),
    ("cell_type_ids", "cell_type_ids"),
)

# 복합 디자인 (예: paired urine+stool) 지원: array 필드에 'all' 모드를 줘서 selected 값 모두 포함하는 doc 만 매치.
# 'all' 이면 must 안에 FieldCondition 을 값 개수만큼 펼침 (= AND). 기본 'any' = MatchAny (OR) backwards compat.
_CONJUNCTION_MODE_KEYS = {
    "modality": "modality_conjunction_mode",
    "disease_ids": "disease_conjunction_mode",
    "tissue_ids": "tissue_conjunction_mode",
    "cell_type_ids": "cell_type_conjunction_mode",
    "organism_taxid": "organism_conjunction_mode",
    "library_strategy": "library_strategy_conjunction_mode",
}


def _conj_mode(req: dict[str, Any], req_key: str) -> str:
    mode_key = _CONJUNCTION_MODE_KEYS.get(req_key)
    if mode_key is None:
        return "any"
    return req.get(mode_key) or "any"


def _build_qdrant_filter(req: dict[str, Any]) -> Filter | None:
    must: list[FieldCondition] = []
    for req_key, payload_key in _ARRAY_FIELDS:
        vals = req.get(req_key)
        if not vals:
            continue
        if req_key in _CONJUNCTION_MODE_KEYS and _conj_mode(req, req_key) == "all":
            # AND: 각 값마다 별도 FieldCondition (Qdrant 가 array contains value 로 평가 → must 가 모두 만족)
            for v in vals:
                must.append(FieldCondition(key=payload_key, match=MatchValue(value=v)))
        else:
            must.append(FieldCondition(key=payload_key, match=MatchAny(any=vals)))
    if req.get("source_db"):
        must.append(FieldCondition(key="source_db", match=MatchAny(any=req["source_db"])))
    if req.get("access_preference") == "open_only":
        must.append(FieldCondition(key="access_type", match=MatchValue(value="open")))
    if req.get("must_have_processed_data"):
        must.append(FieldCondition(key="has_processed_data", match=MatchValue(value=True)))
    return Filter(must=must) if must else None


# Cardinality boost — 디자인 의도 마커가 쿼리에 있으면 (paired, matched, multi-X, cross-, comparative)
# doc 의 facet cardinality >= 2 인 doc 의 score 를 boost. 워크플로우 진단의 "공유 fix #4".
# Sol 4 (재태깅) 와 동행: tagging 좋아지면 boost 효과 더 큼. tagging 없어도 현재 잘 태깅된 doc 은 우선 노출.
_DESIGN_INTENT_RE = re.compile(
    r"\b(paired|matched|multi[\- ]?(?:tissue|omic|organ|cohort|species|modal|sample)|"
    r"cross[\- ]?species|comparative|co[\- ]?occurrence|longitudinal)\b",
    re.IGNORECASE,
)


def _query_has_design_intent(query_text: str) -> bool:
    return bool(_DESIGN_INTENT_RE.search(query_text))


_CARDINALITY_FACETS = ("tissue_ids", "modality", "organism_taxid", "cell_type_ids", "disease_ids")


def _multi_facet_count(payload: dict[str, Any]) -> int:
    return sum(1 for f in _CARDINALITY_FACETS if len(set(payload.get(f) or [])) >= 2)


class SearchBackendUnavailable(RuntimeError):
    """dense·lexical 둘 다 사용 불가 → 라우터에서 503 으로 변환(원시 500 방지)."""


_BOOLEAN_TOKEN_RE = re.compile(r"\b(?:AND|OR|NOT)\b", re.IGNORECASE)


def _clean_lexical_query(q: str) -> str:
    """BM25 용 쿼리에서 단독 불리언 연산자(AND/OR/NOT)·따옴표·괄호 제거.

    이런 토큰은 multi_match best_fields 에서 코퍼스 대부분을 매칭해 카운트를 부풀린다
    (예: 'AND' 단독이 48만건 매칭). 의미 매칭은 임베딩(dense)이 담당하므로 BM25 입력만
    정리한다. 정리 후 비면 원본 유지. accession(GSE…)·일반어는 영향 없음."""
    cleaned = _BOOLEAN_TOKEN_RE.sub(" ", q or "")
    for ch in ('"', "(", ")"):
        cleaned = cleaned.replace(ch, " ")
    cleaned = " ".join(cleaned.split())
    return cleaned or (q or "")


# Negation-aware lexical: 사용자 쿼리에서 "without X / no X / excluding X / non-X / NOT X" 등을 추출 → BM25 의 must_not 절로 변환.
# embedding 은 negation 못 잡지만 OpenSearch 는 명시적 NOT 가능. 워크플로우 진단 결과 P@5 = 0 에서 출발하는 카테고리라 무조건 도움.
# 패턴은 보수적 (false positive 최소화): 명확한 negation 마커 다음에 1~4 단어 까지만 NOT 대상.
_NEGATION_PATTERNS = [
    re.compile(r"\bwithout\s+([A-Za-z][\w\- ]{1,40}?)(?=\s+(?:and|or|but|in|on|of|for|with|from|the|a|an|samples?|patients?|subjects?|cases?|controls?|history|treatment|therapy)\b|[,.]|$)", re.IGNORECASE),
    re.compile(r"\bexcluding\s+([A-Za-z][\w\- ]{1,40}?)(?=\s+(?:and|or|but|in|on|of|for|with|from|the|a|an|samples?|patients?|subjects?|cases?|controls?)\b|[,.]|$)", re.IGNORECASE),
    re.compile(r"\bnon[\- ]([A-Za-z][\w\-]{1,30})", re.IGNORECASE),
    re.compile(r"\bnever[\- ]([A-Za-z][\w\-]{1,20})", re.IGNORECASE),
    re.compile(r"\bno\s+(?:history\s+of\s+|prior\s+|previous\s+)([A-Za-z][\w\- ]{1,30}?)(?=\s+(?:and|or|but|in|on|of|for|with|from|the|a|an|samples?|patients?|subjects?)\b|[,.]|$)", re.IGNORECASE),
    re.compile(r"\b(?:treatment[\- ]naive|untreated|not\s+treated)\b", re.IGNORECASE),
]
# 휴리스틱: 'treatment-naive' 같은 합성어는 별도 NOT 토큰 매핑 (해당 단어 부재 보다는 'treated' 부재가 더 안전).
_NEGATION_TOKEN_MAP = {
    "treatment-naive": "treated",
    "treatment naive": "treated",
    "untreated": "treated",
    "not treated": "treated",
}


def _extract_negation_tokens(query_text: str) -> list[str]:
    """쿼리에서 부정 대상 단어/구를 뽑아 NOT 검색 토큰 리스트 반환.

    예: "lung cancer without smoking history" → ["smoking history"]
        "breast cancer non-treated samples" → ["treated"]
        "never-smoker lung cancer" → ["smoker"]
    """
    tokens: list[str] = []
    lowered = query_text.lower()
    for phrase, replacement in _NEGATION_TOKEN_MAP.items():
        if phrase in lowered:
            tokens.append(replacement)
    for pat in _NEGATION_PATTERNS[:5]:  # _NEGATION_TOKEN_MAP 패턴은 별도 처리됨
        for m in pat.finditer(query_text):
            captured = m.group(1).strip()
            # 너무 짧거나 일반 단어는 제외 (false positive 방지)
            if 2 <= len(captured) <= 40 and captured.lower() not in {"the", "a", "an", "or", "and"}:
                tokens.append(captured)
    # dedup, 정규화
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        norm = t.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(t.strip())
    return out


def _build_os_filter(req: dict[str, Any]) -> list[dict[str, Any]]:
    f: list[dict[str, Any]] = []
    for req_key, doc_key in _ARRAY_FIELDS:
        vals = req.get(req_key)
        if not vals:
            continue
        if req_key in _CONJUNCTION_MODE_KEYS and _conj_mode(req, req_key) == "all":
            # AND: 각 값마다 'term' clause 를 따로 추가 → filter context AND 로 결합
            for v in vals:
                f.append({"term": {doc_key: v}})
        else:
            f.append({"terms": {doc_key: vals}})
    if req.get("source_db"):
        f.append({"terms": {"source_db": req["source_db"]}})
    if req.get("access_preference") == "open_only":
        f.append({"term": {"access_type": "open"}})
    if req.get("must_have_processed_data"):
        f.append({"term": {"has_processed_data": True}})
    return f


# 쿼리 임베딩 Redis 캐시 — 임베딩은 결정적(모델+쿼리 동일→동일벡터)이라 캐시가 품질중립.
# 반복/인기 쿼리는 임베딩 GPU 단계(warm 2.5s·contention 8~11s)를 완전 skip.
# AI Pick 이 같은 쿼리를 재임베딩해도 캐시 HIT → 검색당 임베딩 GPU 부하 2배 문제 해소.
_EMBED_CACHE_TTL = 60 * 60 * 24  # 24h
_EMBED_CACHE_PREFIX = "gf:embq:"


@lru_cache(maxsize=1)
def _get_redis():
    """프로세스 공용 Redis 클라이언트(translate.py 패턴). REDIS_URL 미설정/실패 시 None → 캐시 비활성."""
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis.asyncio as redis_async

        return redis_async.from_url(url, decode_responses=True)
    except Exception as e:
        logger.warning("redis init failed (embed cache off): %s", type(e).__name__)
        return None


def _embed_cache_key(model: str, query_text: str) -> str:
    h = hashlib.sha256(f"{model}\x00{query_text}".encode()).hexdigest()
    return f"{_EMBED_CACHE_PREFIX}{h}"


async def _embed_query(query_text: str) -> list[float]:
    """ephemeral query 임베딩 — Redis 캐시(결정적·품질중립). 캐시 HIT 시 임베딩 GPU skip.

    ADR 0006: 인덱스는 1024d (Qwen3-Embedding-8B Matryoshka truncate). 쿼리 모델이
    8B (4096d native) 이든 0.6B (1024d native) 이든, Qdrant collection dim 과
    일치시키기 위해 클라이언트 측에서 [:1024] truncate.
    """
    QDRANT_DIM = 1024  # datasets_v2 collection 의 차원 — embeddings.py:EMBED_DIM 과 sync
    ollama_url = os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    model = os.environ.get("OLLAMA_MODEL_EMBED", "qwen3-embedding:0.6b")

    r = _get_redis()
    ck = _embed_cache_key(model, query_text)
    if r is not None:
        try:
            cached = await r.get(ck)
        except Exception as e:
            logger.warning("embed cache get failed: %s", type(e).__name__)
            cached = None
        if cached:
            try:
                v = json.loads(cached)
                if isinstance(v, list) and len(v) >= QDRANT_DIM:
                    return v[:QDRANT_DIM]
            except Exception:
                pass  # 손상 → 재계산

    # qwen3-embedding:8b cold start ~84s (Ollama 측에서 모델 로드).
    # 첫 호출에서 30s timeout → HTTP 500. 120s 로 충분히 늘림.
    async with httpx.AsyncClient(base_url=ollama_url, timeout=120.0) as cli:
        resp = await cli.post("/api/embed", json={"model": model, "input": query_text})
        resp.raise_for_status()
        vec = resp.json()["embeddings"][0]
    if len(vec) < QDRANT_DIM:
        raise RuntimeError(
            f"query embedding dim {len(vec)} < {QDRANT_DIM}: OLLAMA_MODEL_EMBED 가 "
            "1024d 미만 모델로 설정됨. qwen3-embedding:8b 또는 :0.6b 권장."
        )
    result = vec[:QDRANT_DIM]
    if r is not None:
        try:
            await r.set(ck, json.dumps(result), ex=_EMBED_CACHE_TTL)
        except Exception as e:
            logger.warning("embed cache set failed: %s", type(e).__name__)
    return result


async def hybrid_search(req: dict[str, Any]) -> dict[str, Any]:
    """Hybrid search 실행. dict-in / dict-out — router 가 Pydantic 변환.

    req 키:
        query_text          (str, required)
        organism_taxid      (list[int])
        library_strategy    (list[str])
        access_preference   ('any' | 'open_only')
        must_have_processed_data (bool)
        page, page_size     (int)
        mode                ('bm25_only' | 'dense_only' | 'rrf' | 'rrf_rerank', 기본 rrf_rerank)
        corpus              ('production' | 'biocaddie_2016_eval', 기본 production)
    """
    t0 = time.perf_counter()
    requested_mode = str(req.get("mode", "rrf_rerank"))
    trace = _EvaluationTraceState(
        enabled=bool(req.get("_evaluation_trace")),
        requested_mode=requested_mode,
        configuration_sha256=(
            _effective_configuration_sha256()
            if req.get("_evaluation_trace")
            else None
        ),
        translation=("not_needed" if req.get("auto_translate", True) else "disabled"),
        query_understanding=(
            "bypassed"
            if req.get("_skip_qu") and _env_enabled("QUERY_UNDERSTANDING_ENABLED")
            else "used"
            if _env_enabled("QUERY_UNDERSTANDING_ENABLED")
            else "disabled"
        ),
        accession_shortcut_enabled=_env_enabled(
            "ACCESSION_SHORTCUT_ENABLED", default=True
        ),
        cardinality_boost_enabled=_env_enabled(
            "CARDINALITY_BOOST_ENABLED", default=True
        ),
        fallbacks=list(req.get("_forced_fallbacks") or []),
    )
    original_query: str = req["query_text"]
    query_text: str = original_query
    translated_query: str | None = None
    page = max(1, int(req.get("page", 1)))
    page_size = max(1, min(100, int(req.get("page_size", 20))))

    # 자동 비영어 → 영어 번역 (auto_translate=True 일 때).
    # 검색 인덱스의 주 언어가 영어라 비ASCII 문자가 포함된 입력은 영어 검색어로
    # 변환한다. 수동 번역 endpoint 는 모든 입력 언어를 지원하며, 여기서는 영어
    # 쿼리에 불필요한 모델 호출을 더하지 않기 위해 비ASCII 입력만 자동 처리한다.
    import re as _re
    NON_ASCII_RE = _re.compile(r"[^\x00-\x7F]")
    if req.get("auto_translate", True) and NON_ASCII_RE.search(query_text or ""):
        from src.services.translate import translate_query as _translate_q
        try:
            t_en = await _translate_q(query_text, target_lang="en")
            if t_en and t_en.strip() and t_en.lower() != query_text.lower():
                translated_query = t_en
                query_text = t_en  # 이후 검색은 영어로
                trace.translation = "used"
            else:
                trace.translation = "failed"
                trace.fallbacks.append("translation_no_effective_output")
        except Exception as e:
            logger.warning("auto translate failed: %s", type(e).__name__)
            trace.translation = "failed"
            trace.fallbacks.append(f"translation_failed:{type(e).__name__}")

    # ---- Sol 1: query understanding (compound query gap, 2026-06-04) ----
    # Extract structured constraints from the (now-English) query and fill any
    # facet slots the user did NOT explicitly set via the UI. All-or-nothing:
    # any failure -> req[] unchanged -> existing behavior preserved.
    #
    # Gated by QUERY_UNDERSTANDING_ENABLED env (default off) so we can disable
    # instantly via worker restart without code change.
    if _env_enabled("QUERY_UNDERSTANDING_ENABLED") \
            and not req.get("_skip_qu"):
        try:
            from src.services.query_understanding import (
                CONFIDENCE_FLOOR as _QU_CONF_FLOOR,
            )
            from src.services.query_understanding import (
                understand_query as _understand_q,
            )
            qu = await _understand_q(query_text, locale="en")
        except Exception as e:
            logger.warning("query_understanding call failed: %s", type(e).__name__)
            qu = None
            trace.query_understanding = "failed"
            trace.fallbacks.append(f"query_understanding_failed:{type(e).__name__}")

        if qu is None and trace.query_understanding != "failed":
            trace.query_understanding = "failed"
            trace.fallbacks.append("query_understanding_no_output")

        if qu is not None:
            # Map text labels -> CURIEs via OntologyMapper (workers package).
            # Heavy LRU cache is process-wide so repeated labels are free.
            curies: dict[str, list[str]] = {"tissues": [], "diseases": [], "cell_types": []}
            try:
                from src.ontology.mapper import OntologyMapper, lookup_many  # type: ignore
                # Skip facet mapping when model is unconfident — only design_intent
                # passes through (it's additive ranking, never filters).
                if qu.get("confidence", 0.0) >= _QU_CONF_FLOOR:
                    async with OntologyMapper() as _mapper:
                        if qu.get("tissues"):
                            curies["tissues"] = [m.curie for m in await lookup_many(_mapper, qu["tissues"], "uberon")]
                        if qu.get("diseases"):
                            curies["diseases"] = [m.curie for m in await lookup_many(_mapper, qu["diseases"], "mondo")]
                        if qu.get("cell_types"):
                            curies["cell_types"] = [m.curie for m in await lookup_many(_mapper, qu["cell_types"], "cl")]
            except Exception as e:
                logger.warning("query_understanding ontology lookup failed: %s", type(e).__name__)
                trace.query_understanding = "failed"
                trace.fallbacks.append(
                    f"query_understanding_ontology_failed:{type(e).__name__}"
                )

            # MERGE — only fill empty slots, NEVER override user-provided values.
            # (req fields come from HTTP client / UI chips; user intent wins.)
            def _empty(v: Any) -> bool:
                return v is None or (isinstance(v, list) and len(v) == 0)

            if qu.get("confidence", 0.0) >= _QU_CONF_FLOOR:
                if curies["tissues"] and _empty(req.get("tissue_ids")):
                    req["tissue_ids"] = curies["tissues"]
                if curies["diseases"] and _empty(req.get("disease_ids")):
                    req["disease_ids"] = curies["diseases"]
                if curies["cell_types"] and _empty(req.get("cell_type_ids")):
                    req["cell_type_ids"] = curies["cell_types"]
                if qu.get("modality") and _empty(req.get("modality")):
                    req["modality"] = list(qu["modality"])
                if qu.get("organism_taxids") and _empty(req.get("organism_taxid")):
                    req["organism_taxid"] = list(qu["organism_taxids"])

                # Conjunction recommendations — apply ONLY when (a) user did not
                # set a mode (still default 'any'), AND (b) at least 2 values
                # were extracted (single value AND-mode is a no-op or worse).
                _conj_map = {
                    "tissue":    ("tissue_conjunction_mode",    req.get("tissue_ids")),
                    "disease":   ("disease_conjunction_mode",   req.get("disease_ids")),
                    "modality":  ("modality_conjunction_mode",  req.get("modality")),
                    "cell_type": ("cell_type_conjunction_mode", req.get("cell_type_ids")),
                    "organism": ("organism_conjunction_mode",   req.get("organism_taxid")),
                }
                for facet, want_all in (qu.get("conjunction_recommendations") or {}).items():
                    if not want_all:
                        continue
                    mode_key, values = _conj_map.get(facet, (None, None))
                    if mode_key is None:
                        continue
                    if req.get(mode_key, "any") != "any":
                        continue  # user explicitly overrode — respect it
                    if not isinstance(values, list) or len(values) < 2:
                        continue  # single-value AND is a no-op or filter-to-zero
                    req[mode_key] = "all"

            # Observability — log extraction summary (NO raw query text per ADR 0002 T7).
            logger.info(
                "query_understanding: di=%s conf=%.2f tissues=%d diseases=%d cells=%d "
                "mod=%d org=%d conj=%s applied_tissue_curies=%d applied_disease_curies=%d",
                qu.get("design_intent", "none"),
                qu.get("confidence", 0.0),
                len(qu.get("tissues") or []),
                len(qu.get("diseases") or []),
                len(qu.get("cell_types") or []),
                len(qu.get("modality") or []),
                len(qu.get("organism_taxids") or []),
                list((qu.get("conjunction_recommendations") or {}).keys()),
                len(curies["tissues"]),
                len(curies["diseases"]),
            )
    # ---- end Sol 1 ----

    # 후보 풀 깊이는 page/page_size 와 무관하게 고정(=MAX_top_k). 이전엔 page*page_size*1.5 라
    # page_size 에 따라 RRF merge 풀이 달라져 같은 위치가 다른 결과를 주고(랭킹 불안정),
    # servable_total 도 page 마다 변했다. 고정하면 랭킹이 page_size 의 순수 함수 → 안정적이고
    # servable_total 이 일관됨. (200 은 서빙 윈도 상한이므로 더 깊은 페이지는 어차피 불가.)
    top_k = MAX_top_k

    # Mode 분기 + corpus switch (ADR 0006 evaluation)
    mode = requested_mode
    corpus = req.get("corpus", "production")
    qdrant_collection = EVAL_CORPUS_QDRANT.get(corpus, QDRANT_COLLECTION)
    os_index = EVAL_CORPUS_OS.get(corpus, OS_INDEX)

    # Accession 룩업 패턴 감지 — 사용자가 GSE/SRP/PRJNA 등 정확 ID 로 검색 시
    # reranker 가 정확 매치를 demote 하는 케이스 방지 (quality benchmark 2026-05-28 발견).
    # 정확 매치는 BM25 의 source_id^15 가 이미 1위로 올림.
    import re as _re
    ACCESSION_RE = _re.compile(
        r"\b(GSE|GSM|GPL|GDS|SRP|SRX|SRR|SRS|PRJ(?:NA|EB|DB)|ERP|ERX|ERR|ERS|SAMN|SAMD|SAME|GCF|GCA)\d+\b",
        _re.IGNORECASE,
    )
    accession_query = bool(ACCESSION_RE.search(query_text or ""))
    if trace.accession_shortcut_enabled and accession_query and mode == "rrf_rerank":
        # production default 일 때 BM25 단독으로 — source_id^15 boost 가
        # 정확 매치를 1위로 올림. RRF/rerank 는 rank merge 때문에 boost 못 살림.
        mode = "bm25_only"
        trace.accession_shortcut_applied = True

    use_dense = mode in ("dense_only", "rrf", "rrf_rerank")
    use_lexical = mode in ("bm25_only", "rrf", "rrf_rerank")
    use_rerank = mode == "rrf_rerank"

    # 명시적 필드 정렬(최신순/오래된순/표본수) — 후보풀 재정렬로는 '전역 최신'을 놓친다(그 문서가
    # 관련도 top-200 밖이면 풀에 아예 없음). OS sort 절로 전역 정렬된 top-N 을 가져오고, dense·
    # rerank·cardinality 는 끈다(정렬 모드에선 관련도 랭킹 무의미). filters/negation 은 그대로 적용.
    _SORT_OS = {
        "submission_date_desc": {"submission_date": {"order": "desc", "missing": "_last"}},
        "submission_date_asc": {"submission_date": {"order": "asc", "missing": "_last"}},
        "n_samples_desc": {"n_samples": {"order": "desc", "missing": "_last"}},
    }
    os_sort = _SORT_OS.get(req.get("sort", "relevance"))
    field_sort = os_sort is not None
    if field_sort:
        use_dense = False
        use_rerank = False
        use_lexical = True
        if mode != "bm25_only":
            trace.fallbacks.append(f"field_sort_override:{req.get('sort')}")

    qdrant = AsyncQdrantClient(url=os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL))
    os_client = AsyncOpenSearch(
        hosts=[os.environ.get("OPENSEARCH_URL", DEFAULT_OS_URL)],
        http_compress=True, use_ssl=False, verify_certs=False, ssl_show_warn=False,
    )

    try:
        # 1) Embed query (dense 미사용 시 skip)
        # 복원력: 임베딩(Ollama)/Qdrant 장애 시 500 대신 BM25 로 우아하게 강등 (reranker 패턴과 동일).
        qd_hits_points: list[Any] = []
        if use_dense:
            try:
                qvec = await _embed_query(query_text)
                qd_filter = _build_qdrant_filter(req)
                qd_resp = await qdrant.query_points(
                    collection_name=qdrant_collection,
                    query=qvec,
                    limit=top_k,
                    query_filter=qd_filter,
                    with_payload=True,
                )
                qd_hits_points = qd_resp.points
                trace.dense = "used"
            except Exception as e:
                logger.warning("dense retrieval failed (%s) — degrading to lexical/BM25", type(e).__name__)
                trace.dense = "failed"
                trace.fallbacks.append(f"dense_failed:{type(e).__name__}")
                use_dense = False
                use_lexical = True  # 프로덕션은 BM25 로 fallback (결과 0건 방지)
                if mode == "dense_only":
                    mode = "bm25_only"
                qd_hits_points = []

        # 3) OpenSearch top K (lexical 미사용 시 skip)
        os_hits: list[dict[str, Any]] = []
        os_total = 0  # OpenSearch 진짜 매칭 수 (track_total_hits) — total_estimated 용
        if use_lexical:
            os_filters = _build_os_filter(req)
            # Negation tokens — title/abstract 에 해당 단어 있는 doc 은 demote (must_not).
            # embedding 은 negation 못 잡지만 BM25 는 명시적 NOT 가능. 보수적 패턴 (false positive 최소).
            neg_tokens = _extract_negation_tokens(query_text)
            must_not_clauses: list[dict[str, Any]] = []
            for tok in neg_tokens:
                must_not_clauses.append({
                    "multi_match": {
                        "query": tok,
                        "fields": ["title", "abstract"],
                        "type": "phrase",  # 정확 매치만 demote — 부분 매치는 통과 (false positive 최소)
                    }
                })
            os_bool: dict[str, Any] = {
                "must": [{
                    "multi_match": {
                        "query": _clean_lexical_query(query_text),
                        # source_id boost 15 — accession 직접 검색 (예: "GSE317412")
                        # 시 해당 데이터셋이 BM25 상위에 잡힘.
                        "fields": [
                            "source_id^15",
                            "title^3",
                            "abstract",
                            "platform",
                            "library_strategy",
                        ],
                        "type": "best_fields",
                    }
                }],
                "filter": os_filters,
            }
            if must_not_clauses:
                os_bool["must_not"] = must_not_clauses
                logger.info("negation tokens applied: %s", neg_tokens)
            try:
                os_body: dict[str, Any] = {"size": top_k, "track_total_hits": True, "query": {"bool": os_bool}}
                if os_sort is not None:  # 필드 정렬: OS 가 전역 정렬(관련도 아님)
                    os_body["sort"] = [os_sort]
                os_resp = await os_client.search(index=os_index, body=os_body)
                os_hits = os_resp["hits"]["hits"]
                trace.lexical = "used"
                try:
                    os_total = int(os_resp["hits"]["total"]["value"])
                except (KeyError, TypeError, ValueError):
                    os_total = len(os_hits)
            except Exception as e:
                logger.warning("lexical retrieval failed (%s)", type(e).__name__)
                trace.lexical = "failed"
                trace.fallbacks.append(f"lexical_failed:{type(e).__name__}")
                use_lexical = False
                os_hits = []
                os_total = 0

        # 복원력: 두 엔진 모두 실패하면 검색 불가 — 깔끔한 503 으로 변환(라우터에서 처리).
        if not use_dense and not use_lexical:
            raise SearchBackendUnavailable("dense and lexical retrieval both unavailable")

        # 4) Merge — mode 에 따라 RRF 또는 단독 ranker score 채용
        merged: dict[str, HybridHit] = {}
        for rank, p in enumerate(qd_hits_points, start=1):
            did = str(p.id)
            merged[did] = HybridHit(
                dataset_id=did, payload=p.payload or {},
                semantic=float(p.score), semantic_rank=rank,
                rrf=1.0 / (RRF_K + rank) if use_lexical else float(p.score),
            )
        for rank, h in enumerate(os_hits, start=1):
            did = h["_id"]
            payload = h["_source"]
            # 필드 정렬 시 OS 가 _score 를 null 로 준다 → 0.0 처리(순서는 post-rank sort 가 결정).
            score = float(h["_score"]) if h.get("_score") is not None else 0.0
            if did in merged:
                hit = merged[did]
                hit.lexical = score
                hit.lexical_rank = rank
                hit.rrf += 1.0 / (RRF_K + rank)
                # OpenSearch source 의 title/abstract 등을 payload 에 보강
                hit.payload = {**hit.payload, **payload}
            else:
                # lexical 단독 (bm25_only) 또는 dense 가 miss 한 doc
                rrf_init = 1.0 / (RRF_K + rank) if use_dense else score
                merged[did] = HybridHit(
                    dataset_id=did, payload=payload,
                    lexical=score, lexical_rank=rank,
                    rrf=rrf_init,
                )

        # 5) Sort
        if mode == "bm25_only":
            ordered = sorted(merged.values(), key=lambda x: x.lexical or 0.0, reverse=True)
        elif mode == "dense_only":
            ordered = sorted(merged.values(), key=lambda x: x.semantic or 0.0, reverse=True)
        else:
            ordered = sorted(merged.values(), key=lambda x: x.rrf, reverse=True)
        # total_estimated = 진짜 매칭 수 추정(OS track_total_hits). 텍스트/복합(fallback) 쿼리는
        # 정확한 대규모 카운트. 단, QU 가 facet 하드필터를 주입한 경우 OS term 필터가 analyzed
        # 필드에서 과소집계 → 단일-facet 쿼리는 카운트가 작게 나올 수 있음(결과 자체는 Qdrant
        # 필터로 정확). 정확 카운트는 후속(Qdrant payload index + count) 과제.
        total = max(os_total, len(ordered))

        # 5b) Cross-encoder rerank (mode == rrf_rerank 일 때만)
        if use_rerank:
            try:
                from src.services.reranker import is_available as rerank_available
                from src.services.reranker import rerank_pairs, rerank_top_n

                rerank_n = rerank_top_n()
                if not rerank_available():
                    trace.reranker = "failed"
                    trace.fallbacks.append("reranker_unavailable")
                elif len(ordered) == 0:
                    # The configured path was available but had no candidates to score.
                    trace.reranker = "used"
                else:
                    top = ordered[:rerank_n]
                    docs = []
                    for h in top:
                        p = h.payload
                        title = p.get("title") or ""
                        abstract = (p.get("abstract") or "")[:900]
                        # Sol 5 — 구조화 메타데이터를 텍스트로 주입.
                        # cross-encoder 가 'paired'/'matched' 같은 디자인 의도를
                        # tissue/modality 카운트로 disambiguate 할 수 있도록.
                        meta_lines: list[str] = []
                        tissues = p.get("tissue_ids") or []
                        modality = p.get("modality") or []
                        if tissues:
                            meta_lines.append(
                                f"tissues ({len(set(tissues))}): {', '.join(sorted(set(tissues)))}"
                            )
                        if modality:
                            meta_lines.append(
                                f"modality ({len(set(modality))}): {', '.join(sorted(set(modality)))}"
                            )
                        cohort = p.get("cohort_design") if isinstance(p.get("cohort_design"), dict) else None
                        design_type = (cohort or {}).get("design_type")
                        if design_type:
                            meta_lines.append(f"design: {design_type}")
                        n_samples = p.get("n_samples")
                        if n_samples:
                            meta_lines.append(f"n_samples: {n_samples}")
                        meta_block = ("\n" + "\n".join(meta_lines) + "\n") if meta_lines else ""
                        docs.append(f"{title}\n{meta_block}\n{abstract}")
                    # CPU-bound (PyTorch inference). 별도 thread 로 빼서 event loop 비움.
                    import asyncio
                    scores = await asyncio.to_thread(rerank_pairs, query_text, docs)
                    if scores is None or len(scores) != len(top):
                        trace.reranker = "failed"
                        trace.fallbacks.append("reranker_incomplete_output")
                    else:
                        trace.reranker = "used"
                        for h, s in zip(top, scores, strict=True):
                            h.rerank = s
                        # rerank 점수 기준 재정렬 — 못 받은 (top-N 밖) 은 그대로 후순위
                        top_sorted = sorted(
                            top,
                            key=lambda x: x.rerank
                            if x.rerank is not None
                            else float("-inf"),
                            reverse=True,
                        )
                        ordered = top_sorted + ordered[rerank_n:]
            except Exception as e:
                logger.warning("reranker failed (%s)", type(e).__name__)
                trace.reranker = "failed"
                trace.fallbacks.append(f"reranker_failed:{type(e).__name__}")

        # 5b') Cardinality boost — 디자인 의도 마커가 쿼리에 있으면 multi-facet doc 점수 강화.
        # rerank 된 top-N 안에서만 적용 (안 본 후보는 그대로). 1.10x~1.25x.
        if (
            trace.cardinality_boost_enabled
            and _query_has_design_intent(query_text)
            and len(ordered) > 0
            and not field_sort
        ):
            boost_n = 0
            boost_top = ordered[: min(len(ordered), 20)]
            for h in boost_top:
                mfc = _multi_facet_count(h.payload)
                if mfc >= 1:
                    mult = 1.0 + min(0.25, 0.05 + 0.05 * mfc)
                    if h.rerank is not None:
                        h.rerank *= mult
                    h.rrf *= mult
                    boost_n += 1
            if boost_n:
                trace.cardinality_boost_applied = True
                logger.info("cardinality boost applied to %d/%d top hits", boost_n, len(boost_top))
                # 재정렬
                if use_rerank:
                    # rerank 안 된 항목(None)이나 0.0 점수를 -inf 로 밀어내지 않도록:
                    # rerank 있으면 rerank, 없으면 rrf 로 정렬(혼합 윈도우 순서 보존).
                    boost_top = sorted(
                        boost_top,
                        key=lambda x: x.rerank if x.rerank is not None else x.rrf,
                        reverse=True,
                    )
                else:
                    boost_top = sorted(boost_top, key=lambda x: x.rrf, reverse=True)
                ordered = boost_top + ordered[len(boost_top):]

        # 5c) Post-rank sort — 후보 retrieval 결과를 사용자 지정 필드로 재정렬.
        # NULL 은 후순위 (각 정렬 방향에 따라 가장 작은 값 / 가장 큰 값 부여).
        sort_mode = req.get("sort", "relevance")
        if sort_mode == "n_samples_desc":
            ordered = sorted(
                ordered, key=lambda x: (x.payload.get("n_samples") or 0), reverse=True
            )
        elif sort_mode == "submission_date_desc":
            ordered = sorted(
                ordered,
                key=lambda x: (x.payload.get("submission_date") or ""),
                reverse=True,
            )
        elif sort_mode == "submission_date_asc":
            ordered = sorted(
                ordered,
                key=lambda x: (x.payload.get("submission_date") or "9999-12-31"),
            )

        start = (page - 1) * page_size
        chunk = ordered[start : start + page_size]

        # 6) Facets — 전체 후보(merged) 기준 카운트.
        # 단일 패스로 5개 facet 을 동시 집계 (이전: 필드별 5x O(n) 별도 루프).
        # 출력은 이전과 동일 — array 필드는 값별 +1, scalar 는 truthy 일 때 +1.
        array_fields = ("modality", "disease_ids", "tissue_ids", "cell_type_ids")
        scalar_fields = ("source_db",)
        _facet_counts: dict[str, dict[str, int]] = {
            field: {} for field in (*array_fields, *scalar_fields)
        }
        for hit in ordered:
            payload = hit.payload
            for field in array_fields:
                counts = _facet_counts[field]
                for v in (payload.get(field) or []):
                    counts[v] = counts.get(v, 0) + 1
            for field in scalar_fields:
                v = payload.get(field)
                if v:
                    counts = _facet_counts[field]
                    counts[v] = counts.get(v, 0) + 1

        def _to_facet_list(counts: dict[str, int], top: int = 30) -> list[dict[str, Any]]:
            return [
                {"value": k, "count": v}
                for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top]
            ]

        facets = {
            "modality": _to_facet_list(_facet_counts["modality"]),
            "source_db": _to_facet_list(_facet_counts["source_db"]),
            "disease_ids": _to_facet_list(_facet_counts["disease_ids"]),
            "tissue_ids": _to_facet_list(_facet_counts["tissue_ids"]),
            "cell_type_ids": _to_facet_list(_facet_counts["cell_type_ids"]),
        }

        # chunk 의 dataset_id 들로 dataset_sources 한 번에 JOIN (top-K 만 쿼리하므로 빠름).
        # UUID cast 가 인덱스 무효화하지 않도록 uuid[] 로 직접 캐스팅 (Seq Scan 회귀 방지, 2026-05-30).
        sources_by_dataset: dict[str, list[dict[str, Any]]] = {}
        if chunk:
            chunk_ids = [hit.dataset_id for hit in chunk]
            import asyncpg as _apg
            pg_url = (os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL", "")).replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            if pg_url:
                try:
                    pg_conn = await _apg.connect(pg_url)
                    try:
                        rows = await pg_conn.fetch(
                            """
                            SELECT dataset_id::text AS dataset_id, source_db, source_id, raw_url, is_primary
                            FROM dataset_sources
                            WHERE dataset_id = ANY($1::uuid[])
                            ORDER BY is_primary DESC, source_db ASC
                            """,
                            chunk_ids,
                        )
                        for r in rows:
                            sources_by_dataset.setdefault(r["dataset_id"], []).append({
                                "source_db": r["source_db"],
                                "source_id": r["source_id"],
                                "raw_url": r["raw_url"],
                                "is_primary": r["is_primary"],
                            })
                    finally:
                        await pg_conn.close()
                except Exception as e:
                    logger.warning("dataset_sources join failed: %s", type(e).__name__)

        results: list[dict[str, Any]] = []
        for hit in chunk:
            p = hit.payload
            abstract_full = p.get("abstract") or ""
            results.append({
                "dataset_id": hit.dataset_id,
                "source_db": p.get("source_db") or "",
                "source_id": p.get("source_id") or "",
                "title": p.get("title"),
                "abstract_snippet": abstract_full[:240] if abstract_full else None,
                "score": hit.rerank if hit.rerank is not None else hit.rrf,
                "score_breakdown": {
                    "semantic": hit.semantic,
                    "lexical": hit.lexical,
                    "rrf": hit.rrf,
                    "rerank": hit.rerank,
                },
                "modality": p.get("modality") or [],
                "organism_taxid": p.get("organism_taxid") or [],
                "disease_ids": p.get("disease_ids") or [],
                "tissue_ids": p.get("tissue_ids") or [],
                "cell_type_ids": p.get("cell_type_ids") or [],
                "library_strategy": p.get("library_strategy"),
                "platform": p.get("platform"),
                "access_type": p.get("access_type") or "open",
                "has_processed_data": bool(p.get("has_processed_data", False)),
                "submission_date": p.get("submission_date"),
                "n_samples": p.get("n_samples"),
                "sources": sources_by_dataset.get(hit.dataset_id, []),
            })

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "results": results,
            "facets": facets,
            "page": page,
            "page_size": page_size,
            "total_estimated": total,
            # 실제로 페이지로 넘겨볼 수 있는 결과 수(후보 윈도 = dense+lexical 병합 union).
            # total_estimated 는 매칭 추정치(수만)이지만 서빙 가능한 건 이만큼 → 정직한 페이지네이션 근거.
            "servable_total": len(ordered),
            "latency_ms": latency_ms,
            "query_id": str(uuid.uuid4()),
            "original_query": original_query if translated_query else None,
            "translated_query": translated_query,
            "evaluation_trace": trace.as_dict(),
        }
    finally:
        await qdrant.close()
        await os_client.close()
