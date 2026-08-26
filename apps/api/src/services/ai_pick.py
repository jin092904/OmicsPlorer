"""AI's Pick — gemma4-curated top picks over the hybrid-search candidate set.

Feature (project_ai_pick_feature.md, 2026-06-11): surface 4 AI-curated datasets at
the top of the search results with a one-line Korean reason for each. Additive UI
feature — it must NEVER break or slow the existing search.

Flow:
    1. Reuse hybrid_search() to fetch the top ~15 reranked candidates for the SAME
       query + filters the user already searched with.
    2. Send the query + a numbered candidate block to local Ollama gemma4:31b
       (NO `format` schema — prompt-only JSON enforcement per Gemma inventory
       caveat; parsed + defensively validated here, mirroring query_understanding).
    3. Validate the returned {index, reason} picks, join indices back to the full
       result objects, and assemble AIPickItem-shaped dicts.
    4. Cache the assembled response in Redis (gf:aipick:v1:{sha256}, 24h). nocache
       bypasses the cache GET and overwrites (the "다시 추천 / regenerate" button).

Safety / graceful degradation (every failure path returns picks=[], never raises):
    - Feature flag AI_PICK_ENABLED (default OFF) → picks=[] so the UI hides the card.
    - No search results → picks=[].
    - Ollama down / timeout / parse / validate failure → picks=[] (logged warning).
    - Redis down → still works, just regenerates each load (cached=False).

ADR 0002 T7: cache key is sha256 of the normalized query+filters — no plaintext
query in Redis or logs. ADR 0003: Ollama local-only (httpx direct, no LLM SDK).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import httpx
import redis.asyncio as redis_async

from src.services.ai_pick_prompt import MAX_CANDIDATES, MAX_PICKS, build_prompt
from src.services.search import hybrid_search

logger = logging.getLogger(__name__)

# Bump on prompt/schema/model change → embedded in cache value (version-skew guard)
# and the "v1" in CACHE_NAMESPACE invalidates the whole prefix atomically.
AIPICK_VERSION = "aipick-v2-gemma4-2026-06-15"  # v2: locale-aware reason (ko/en)
CACHE_NAMESPACE = "gf:aipick:v1:"
CACHE_TTL = 60 * 60 * 24  # 24h, matches translate / query_understanding

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma4:31b"  # batch-quality model (project_batch_model_choice)
# Warm gemma4:31b ~2-4s; cold start can be 30-90s. 120s matches query_understanding.
DEFAULT_TIMEOUT_S = 120.0

_REASON_MAX = 120  # hard truncate the Korean one-liner (matches schema maxLength)


# -- Redis singleton ----------------------------------------------------------


@lru_cache(maxsize=1)
def get_redis() -> redis_async.Redis | None:
    """Process-wide Redis client (lru_cache singleton). None if REDIS_URL unset."""
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    return redis_async.from_url(url, decode_responses=True)


def _enabled() -> bool:
    """Feature flag — read each call so env toggles take effect on the next request."""
    return os.environ.get("AI_PICK_ENABLED", "0").strip() in {"1", "true", "yes", "on"}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- Cache key ----------------------------------------------------------------

# Conjunction-mode keys that change which datasets are eligible → part of the key.
_CONJ_KEYS = (
    "tissue_conjunction_mode",
    "disease_conjunction_mode",
    "modality_conjunction_mode",
    "cell_type_conjunction_mode",
    "organism_conjunction_mode",
    "library_strategy_conjunction_mode",
)


def _cache_key(req: dict[str, Any]) -> str:
    """Deterministic over query + filters (incl. source_db, corpus, lang).

    Excludes page/page_size/sort/mode/nocache/auto_translate (page-independent).
    source_db·corpus·lang ARE included — they change candidate eligibility / reason
    language, so they must NOT share a cache entry. sha256 → no plaintext in Redis.
    """
    norm = {
        "q": (req.get("query_text") or "").strip().lower(),
        "modality": sorted(req.get("modality") or []),
        "tissue_ids": sorted(req.get("tissue_ids") or []),
        "disease_ids": sorted(req.get("disease_ids") or []),
        "cell_type_ids": sorted(req.get("cell_type_ids") or []),
        "organism_taxid": sorted(req.get("organism_taxid") or []),
        "library_strategy": sorted(req.get("library_strategy") or []),
        # source_db(출처 필터)·corpus 는 후보 자체를 바꾼다 → 캐시키 포함(교차오염 방지).
        "source_db": sorted(req.get("source_db") or []),
        "corpus": req.get("corpus", "production"),
        "access_preference": req.get("access_preference", "open_only"),
        "must_have_processed_data": bool(req.get("must_have_processed_data", False)),
        "conj": {k: req.get(k, "any") for k in _CONJ_KEYS},
        # reason 언어가 다르면 별도 캐시 (en/ko 충돌 방지).
        "lang": "en" if (req.get("lang") == "en") else "ko",
    }
    blob = json.dumps(norm, separators=(",", ":"), sort_keys=True)
    return CACHE_NAMESPACE + hashlib.sha256(blob.encode("utf-8")).hexdigest()


# -- gemma response parse + validate ------------------------------------------


def _parse_response(raw: str) -> Any:
    """Strip optional ```json fences then json.loads. Mirrors query_understanding."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"```$", "", raw).strip()
    return json.loads(raw)


def _validate(parsed: Any, n_candidates: int) -> list[dict[str, Any]]:
    """Defensive post-parse validation → list of {index, reason}.

    NO `format` schema is sent to Ollama (prompt-only JSON, per Gemma caveat), so
    this is the enforcement. Raises ValueError on a structural failure (caller
    catches → picks=[]). Out-of-range / duplicate picks are DROPPED, not fatal.
    """
    if not isinstance(parsed, dict):
        raise ValueError("response must be object")
    picks_raw = parsed.get("picks")
    if not isinstance(picks_raw, list):
        raise ValueError("picks must be list")

    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for item in picks_raw:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        # Hallucination guard: index must be a valid 0-based candidate position.
        if idx < 0 or idx >= n_candidates:
            logger.warning("ai_pick: dropped out-of-range index=%s (n=%d)", idx, n_candidates)
            continue
        if idx in seen:  # model repeated a pick — first occurrence wins
            continue
        reason = item.get("reason")
        if not isinstance(reason, str):
            continue
        reason = reason.strip()
        if not reason:
            continue
        seen.add(idx)
        out.append({"index": idx, "reason": reason[:_REASON_MAX]})
        if len(out) >= MAX_PICKS:  # belt-and-suspenders vs. maxItems
            break
    return out


# -- gemma call ---------------------------------------------------------------


async def _gemma_pick(
    query_text: str,
    candidates: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    model: str | None = None,
    disease_labels: dict[str, str] | None = None,
    tissue_labels: dict[str, str] | None = None,
    lang: str = "ko",
) -> list[dict[str, Any]]:
    """Call gemma4 to pick 0..4 candidates. Returns [] on ANY failure (never raises).

    Returns a list of {index, reason} where index is the 0-based position into the
    `candidates` array (caller joins back to the full result object).
    disease_labels/tissue_labels: CURIE→사람 라벨 맵 (프롬프트에 라벨로 노출 — 추천 품질).
    """
    if not candidates:
        return []

    # S9(① 지연 근본해결): AI Pick(gemma4)을 임베더·번역(qwen3)이 도는 OLLAMA_URL 과 분리된
    # 인스턴스로 보낼 수 있게 AIPICK_OLLAMA_URL 우선. 미설정 시 기존 동작(OLLAMA_URL→DEFAULT) 유지.
    # 이유: :11435 에 embed+translate+gemma4 3모델이 몰리면 MAX_LOADED=2 로 thrashing(콜드 30~80s).
    #       gemma4 만 idle :11434 로 빼면 :11435 는 2모델로 안정.
    url = (
        base_url
        or os.environ.get("AIPICK_OLLAMA_URL")
        or os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    ).rstrip("/") + "/api/generate"
    model_name = model or os.environ.get(
        "OLLAMA_MODEL_AIPICK",
        os.environ.get(
            "OLLAMA_MODEL_QU",
            os.environ.get("OLLAMA_MODEL_EXTRACTION", DEFAULT_MODEL),
        ),
    )
    body = {
        "model": model_name,
        "prompt": build_prompt(
            query_text, candidates,
            disease_labels=disease_labels, tissue_labels=tissue_labels, lang=lang,
        ),
        # NO "format" key — prompt-only JSON enforcement (Gemma inventory caveat).
        "stream": False,
        # gemma4 thinking off — JSON 직출력만.
        "think": False,
        "options": {
            "temperature": 0.2,  # mild variation → "re-roll" UX on refresh
            "num_predict": 700,  # 4 picks × short reason; cap safely above.
            # S9: gemma4 Modelfile 기본 ctx(262144)는 VRAM 73GB 점유. AI Pick 후보 블록은 짧아
            # 16K 면 충분 → VRAM ~25GB 로 축소, 공유 GPU 반환 + 공존 용이. (env 로 조정 가능)
            "num_ctx": int(os.environ.get("AIPICK_NUM_CTX", "8192")),
        },
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("ai_pick ollama failed: %s", type(e).__name__)
        return []

    raw = data.get("response", "")
    try:
        parsed = _parse_response(raw)
    except json.JSONDecodeError:
        logger.warning("ai_pick json parse failed | raw_head=%r", raw[:200])
        return []
    try:
        return _validate(parsed, len(candidates))
    except (ValueError, TypeError) as e:
        logger.warning("ai_pick validation failed: %s", type(e).__name__)
        return []


# -- Response assembly --------------------------------------------------------


def _to_pick_item(candidate: dict[str, Any], reason: str) -> dict[str, Any]:
    """Join a validated {index, reason} back to the full hybrid_search result.

    Shapes the AIPickItem the schema expects — the bare {index, reason} is never
    transported; the candidate's metadata lives in the response only.
    """
    return {
        "dataset_id": candidate.get("dataset_id"),
        "source_db": candidate.get("source_db"),
        "source_id": candidate.get("source_id"),
        "title": candidate.get("title"),
        "abstract_snippet": candidate.get("abstract_snippet"),
        "score": float(candidate.get("score") or 0.0),
        "modality": candidate.get("modality") or [],
        "n_samples": candidate.get("n_samples"),
        "reason": reason,
    }


def _empty(query_id: str | None, cached: bool) -> dict[str, Any]:
    return {
        "picks": [],
        "cached": cached,
        "generated_at": _now_iso(),
        "model_version": AIPICK_VERSION,
        "query_id": query_id,
    }


# -- Public API ---------------------------------------------------------------


async def generate_ai_pick(
    req: dict[str, Any],
    *,
    nocache: bool = False,
    base_url: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Generate (or serve from cache) the AI's Pick response for a search request.

    `req` is a SearchRequest-shaped dict (same query_text + filters as /search).
    `nocache=True` skips the cache GET and overwrites the cache (refresh button).

    ALWAYS returns an AIPickResponse-shaped dict (never raises, never 5xx):
        {picks: [...], cached: bool, generated_at: str, model_version: str,
         query_id: str | None}
    On disabled/empty/failure → picks=[] so the UI hides the card.
    """
    # Feature flag — disabled returns an empty payload (no search, no LLM).
    if not _enabled():
        return _empty(None, cached=False)

    if not (req.get("query_text") or "").strip():
        return _empty(None, cached=False)

    r = get_redis()
    ckey = _cache_key(req)

    # 1) Cache GET (skipped entirely on nocache → forces regenerate + overwrite).
    if not nocache and r is not None:
        try:
            cached = await r.get(ckey)
        except Exception as e:
            logger.warning("ai_pick redis get failed: %s", type(e).__name__)
            cached = None
        if cached:
            try:
                value = json.loads(cached)
                if isinstance(value, dict) and value.get("model_version") == AIPICK_VERSION:
                    value["cached"] = True
                    return value
                # version mismatch → fall through, regenerate
            except json.JSONDecodeError:
                logger.warning("ai_pick cache corrupt — regenerating")

    # 2) Generate — fetch top candidates via the hybrid pipeline.
    # mode='rrf' (리랭크 생략): gemma 가 15개를 어차피 재선별하므로 cross-encoder 중복 패스 제거
    # → /search 가 이미 돌린 무거운 리랭크를 AI Pick 이 또 돌리지 않음(중복 작업 감소).
    search_req = {**req, "page": 1, "page_size": MAX_CANDIDATES, "mode": "rrf"}
    search_req.pop("nocache", None)  # not a SearchRequest field
    try:
        search_result = await hybrid_search(search_req)
    except Exception as e:
        logger.warning("ai_pick hybrid_search failed: %s", type(e).__name__)
        return _empty(None, cached=False)

    candidates = search_result.get("results") or []
    query_id = search_result.get("query_id")
    if not candidates:
        value = _empty(query_id, cached=False)
        await _cache_set(r, ckey, value)
        return value

    # CURIE → 사람 라벨 해석 (gemma 가 MONDO:xxx 대신 "breast cancer" 를 보도록 → 추천 품질).
    # 실패해도 라벨 없이 진행(graceful).
    disease_labels: dict[str, str] = {}
    tissue_labels: dict[str, str] = {}
    try:
        from src.services.ontology import lookup_labels
        dis = {c for cand in candidates for c in (cand.get("disease_ids") or [])}
        tis = {c for cand in candidates for c in (cand.get("tissue_ids") or [])}
        if dis:
            disease_labels = await lookup_labels(dis)
        if tis:
            tissue_labels = await lookup_labels(tis)
    except Exception as e:
        logger.warning("ai_pick label lookup failed: %s", type(e).__name__)

    # 한국어 쿼리는 번역본으로 프롬프트(후보가 영어 쿼리로 뽑혔으므로 일관성).
    prompt_query = search_result.get("translated_query") or req["query_text"]

    # 3) gemma pick (all-or-nothing; [] on any failure). reason 언어 = req.lang(en/ko).
    pick_lang = "en" if (req.get("lang") == "en") else "ko"
    picks_idx = await _gemma_pick(
        prompt_query, candidates, base_url=base_url, model=model,
        disease_labels=disease_labels, tissue_labels=tissue_labels, lang=pick_lang,
    )

    # 4) Join indices back to full candidate objects.
    picks = [_to_pick_item(candidates[p["index"]], p["reason"]) for p in picks_idx]

    value = {
        "picks": picks,
        "cached": False,
        "generated_at": _now_iso(),
        "model_version": AIPICK_VERSION,
        "query_id": query_id,
    }

    # 5) Cache SET (overwrites on nocache; resets 24h TTL). Failure does not block.
    await _cache_set(r, ckey, value)
    return value


async def _cache_set(r: redis_async.Redis | None, ckey: str, value: dict[str, Any]) -> None:
    if r is None:
        return
    try:
        await r.set(ckey, json.dumps(value, separators=(",", ":")), ex=CACHE_TTL)
    except Exception as e:
        logger.warning("ai_pick redis set failed: %s", type(e).__name__)


# -- CLI dry-run --------------------------------------------------------------


def _main() -> int:
    """python -m src.services.ai_pick "<query>" [--nocache] [--model ...]

    Forces AI_PICK_ENABLED on for the dry run. Requires Ollama (gemma4) up.
    """
    ap = argparse.ArgumentParser(description="AI's Pick dry-run")
    ap.add_argument("query", help="search query text")
    ap.add_argument("--nocache", action="store_true")
    ap.add_argument("--no-redis", action="store_true", help="unset REDIS_URL for this run")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()

    os.environ["AI_PICK_ENABLED"] = "1"
    if args.no_redis:
        os.environ.pop("REDIS_URL", None)
        get_redis.cache_clear()  # type: ignore[attr-defined]

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = asyncio.run(
        generate_ai_pick(
            {"query_text": args.query},
            nocache=args.nocache,
            base_url=args.base_url,
            model=args.model,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
