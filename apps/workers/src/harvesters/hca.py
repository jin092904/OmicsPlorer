"""HCA (Human Cell Atlas) harvester — Azul Data Browser API.

L0 (Public) 데이터만 다룬다.

검증 출처 (docs/external-apis.md §4, 직접 호출 2026-05-06):
- Base URL: https://service.azul.data.humancellatlas.org/
- /index/projects?size=N&search_after=... — 페이지네이션
- 각 hit 의 top-level 키: protocols, entryId, sources, projects, samples, specimens,
  cellLines, donorOrganisms, organoids, cellSuspensions, dates, fileTypeSummaries
- projects[0] 키: projectId, projectTitle, projectShortname, projectDescription,
  estimatedCellCount, accessions (GEO/SRA cross-ref), dataUseRestriction, accessible

GEO/SRA 와 다른 점 — HCA 는 organism / organ / cellType / library 를 사전에 정규화해서 제공.
LLM 추출 거의 불필요. OLS4 lookup 만 (free-text 'brain' → UBERON:0000955) 하면 된다.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
from tenacity import AsyncRetrying

from .base import Harvester
from .geo import _RETRY_POLICY  # 공용 retry policy 재사용

logger = logging.getLogger(__name__)

HCA_BASE = "https://service.azul.data.humancellatlas.org/"
PAGE_SIZE = 15  # Azul 의 max 는 사용처에 따라 다름 — 보수적 default
DEFAULT_TIMEOUT_S = 30.0


class HcaHarvester(Harvester):
    """HCA Project records via Azul.

    semantics:
        - source_id = HCA projectId (UUID).
        - fetch_raw 는 단일 project entry hit 의 dict 전체를 반환 (raw_metadata 보존용).
        - list_updated_since 는 현재 모든 project 를 yield — Azul 는 지난 변경 시각 필터를
          공식 API 로 제공하지 않음. 후속 PR 에서 client-side 필터 (entry.dates.aggregateLastModifiedDate
          비교) 로 보강.
    """

    source_db = "HCA"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rps: float = 5.0,  # Azul 는 명시 rate limit 없음 — 보수적 5rps
    ) -> None:
        self._min_interval_s = 1.0 / rps
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client = client or httpx.AsyncClient(
            base_url=HCA_BASE,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": "OmicsPlorer/0.1.0"},
        )
        # entryId → 캐시된 hit (paginated list 가 이미 모든 메타를 반환하므로 fetch_raw 호출 절약)
        self._index_cache: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HcaHarvester:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = max(0.0, self._next_at - now)
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = max(now, self._next_at) + self._min_interval_s

    async def _get_json(self, url_or_path: str, params: dict | None = None) -> dict:
        async for attempt in AsyncRetrying(**_RETRY_POLICY):
            with attempt:
                await self._throttle()
                # url_or_path 가 절대 URL 이면 (pagination next) 그대로
                if url_or_path.startswith("http"):
                    resp = await self._client.get(url_or_path, params=params)
                else:
                    resp = await self._client.get(url_or_path, params=params)
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError("unreachable")

    async def list_updated_since(self, since: datetime) -> AsyncIterator[str]:
        """모든 HCA project 의 entryId 를 yield. since 는 현재 client-side 필터로만 적용.

        each hit 의 dates.aggregateLastModifiedDate 가 since 이전이면 skip.
        """
        next_url: str | None = None
        params = {"size": str(PAGE_SIZE)}
        total_yielded = 0
        while True:
            if next_url is None:
                payload = await self._get_json("/index/projects", params=params)
            else:
                payload = await self._get_json(next_url)
            hits = payload.get("hits") or []
            if not hits:
                break
            for h in hits:
                entry_id = h.get("entryId")
                if not entry_id:
                    continue
                # client-side 시간 필터
                if not _passes_since(h, since):
                    continue
                self._index_cache[entry_id] = h
                yield entry_id
                total_yielded += 1
            pag = payload.get("pagination") or {}
            next_url = pag.get("next")
            if not next_url:
                break
            params = None  # next URL 은 자체에 cursor 포함
        logger.info("hca harvest: yielded %d projects", total_yielded)

    async def fetch_raw(self, source_id: str) -> dict:
        """list_updated_since 가 캐시한 hit 을 반환. 캐시 미스 시 단건 fetch.

        Azul `/index/projects?filters=...` 로 단건도 가능하지만, paginated list 가 이미
        full payload 를 반환하므로 캐시 hit 률 100%.
        """
        cached = self._index_cache.get(source_id)
        if cached is not None:
            return {"hit": cached}
        # cache miss — 단건 fetch (rare path)
        payload = await self._get_json(
            "/index/projects",
            params={"filters": f'{{"projectId":{{"is":["{source_id}"]}}}}'},
        )
        hits = payload.get("hits") or []
        if not hits:
            raise ValueError(f"HCA projectId {source_id!r} not found")
        return {"hit": hits[0]}


def _passes_since(hit: dict[str, Any], since: datetime) -> bool:
    """hit.dates.aggregateLastModifiedDate >= since 면 통과."""
    dates_list = hit.get("dates") or []
    if not dates_list:
        return True
    last_mod = (dates_list[0] or {}).get("aggregateLastModifiedDate")
    if not last_mod:
        return True
    try:
        # 'YYYY-MM-DDTHH:MM:SS.ffffff+00:00'
        d = datetime.fromisoformat(last_mod.replace("Z", "+00:00"))
        return d >= since
    except ValueError:
        return True
