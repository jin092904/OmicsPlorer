"""OLS4 기반 ontology mapper — free-text 라벨 → curie (`MONDO:xxxxxxx` 등).

마스터 플랜 §5.3 의 v0 단순 구현:
- `/api/select?q=<text>&ontology=<onto>` 로 top-1 매칭 가져옴
- 결과 confidence 가 낮으면 (label 이 query 와 거의 일치하지 않으면) human review queue 로 보낼 수 있도록
  best-guess 와 함께 점수도 반환
- LRU cache (in-memory) — 같은 process 안에서 동일 (text, ontology) 재요청 안 함

Threshold: 정확 매칭 또는 exact synonym 만 자동 채택. 그 외는 None 반환 (caller 가 누락 처리).
이 보수적 정책은 학술 사용자가 노이즈에 민감하다는 마스터 플랜 §1.2 원칙을 따른다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

DEFAULT_OLS4_URL = "https://www.ebi.ac.uk/ols4/api"
Ontology = Literal["mondo", "uberon", "cl", "efo"]


@dataclass(frozen=True)
class Match:
    curie: str  # 예: "MONDO:0005061"
    label: str
    matched_synonym: str | None  # exact synonym 으로 매칭됐을 때 어떤 synonym 이었는지
    ontology: str


def _is_exact(query: str, label: str, synonyms: list[str]) -> tuple[bool, str | None]:
    """query 가 label 또는 exact_synonym 중 하나와 (case-insensitive, trimmed) 일치하는지."""
    q = query.strip().lower()
    if q == (label or "").strip().lower():
        return True, None
    for s in synonyms or []:
        if q == (s or "").strip().lower():
            return True, s
    return False, None


class OntologyMapper:
    """OLS4 wrapper.

    - 단일 process 내부 LRU cache (None 결과도 cache).
    - 외부 호출 비용을 고려해 동시 호출 제어는 caller (asyncio.Semaphore 등) 가 담당.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OLS4_URL,
        client: httpx.AsyncClient | None = None,
        cache_size: int = 4096,
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=15.0)
        self._cache: dict[tuple[str, str], Match | None] = {}
        self._cache_size = cache_size

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> OntologyMapper:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def lookup(self, text: str, ontology: Ontology) -> Match | None:
        if not text or not text.strip():
            return None
        key = (text.strip().lower(), ontology)
        if key in self._cache:
            return self._cache[key]

        # /api/search?exact=true 는 label / exact_synonym 정확 매칭을 1순위로 반환.
        # 흔한 단어 ('lung', 'blood' 등) 의 canonical term 을 안정적으로 찾는다.
        try:
            resp = await self._client.get(
                "/search",
                params={"q": text, "ontology": ontology, "rows": "5", "exact": "true"},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("OLS4 search failed text=%r onto=%s err=%s", text, ontology, e)
            return self._memoize(key, None)

        docs = data.get("response", {}).get("docs", [])
        for doc in docs:
            curie = doc.get("obo_id")
            label = doc.get("label", "")
            synonyms = doc.get("exact_synonyms") or []
            if not curie:
                continue
            ok, syn = _is_exact(text, label, synonyms)
            if ok:
                return self._memoize(
                    key, Match(curie=curie, label=label, matched_synonym=syn, ontology=ontology)
                )
        # 정확 매칭 없음 — None 반환 (학술 사용자 noise tolerance 낮음)
        return self._memoize(key, None)

    def _memoize(self, key: tuple[str, str], value: Match | None) -> Match | None:
        if len(self._cache) >= self._cache_size:
            # 단순 FIFO 풀어내기 — pop 첫 키 (Python 3.7+ dict preserves insertion order)
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = value
        return value


# 편의 — 여러 텍스트를 한 ontology 에 lookup
async def lookup_many(
    mapper: OntologyMapper, texts: list[str], ontology: Ontology
) -> list[Match]:
    """결과를 dedup 후 반환 (curie 기준)."""
    seen: dict[str, Match] = {}
    for t in texts:
        m = await mapper.lookup(t, ontology)
        if m is not None and m.curie not in seen:
            seen[m.curie] = m
    return list(seen.values())
