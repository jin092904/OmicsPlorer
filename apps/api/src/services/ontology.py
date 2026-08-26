"""Ontology label lookup — curie 를 사람-친화 라벨로 매핑.

UI 가 facet 의 `MONDO:0005061` 같은 curie 를 사용자에게 보여줄 때 'lung adenocarcinoma'
같은 라벨이 필요. OLS4 `/api/terms` 또는 `/api/search?exact=true` 로 가져오고 in-memory
LRU 로 캐시.

Phase 4 에서 Redis 캐시로 승격 예정.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import httpx

logger = logging.getLogger(__name__)

OLS4_URL = "https://www.ebi.ac.uk/ols4/api"
_CACHE: dict[str, str] = {}
_LOCK = asyncio.Lock()
_CLIENT: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(base_url=OLS4_URL, timeout=10.0)
    return _CLIENT


def _ontology_for(curie: str) -> str | None:
    prefix = curie.split(":", 1)[0].lower()
    return prefix if prefix in {"mondo", "uberon", "cl", "efo"} else None


async def _lookup_one(curie: str) -> str | None:
    onto = _ontology_for(curie)
    if not onto:
        return None
    try:
        resp = await _client().get(
            "/search",
            params={"q": curie, "ontology": onto, "rows": "1", "exact": "true"},
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("OLS4 label lookup failed curie=%s err=%s", curie, e)
        return None
    docs = data.get("response", {}).get("docs") or []
    if not docs:
        return None
    label = docs[0].get("label")
    return label if isinstance(label, str) and label else None


async def lookup_labels(curies: Iterable[str]) -> dict[str, str]:
    """curie 리스트 → {curie: label}. 캐시되지 않은 항목만 OLS4 호출.

    매칭 실패 항목은 결과에 포함하지 않는다 — frontend 는 이 경우 curie 그대로 표시.
    """
    needed = [c for c in dict.fromkeys(curies) if c not in _CACHE]
    if needed:
        async with _LOCK:
            # 잠금 해제 후 다시 확인 — 동시 요청 중복 회피
            still_needed = [c for c in needed if c not in _CACHE]
            if still_needed:
                results = await asyncio.gather(
                    *(_lookup_one(c) for c in still_needed),
                    return_exceptions=True,
                )
                for c, label in zip(still_needed, results):
                    if isinstance(label, str):
                        _CACHE[c] = label
    return {c: _CACHE[c] for c in curies if c in _CACHE}
