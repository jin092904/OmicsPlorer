"""GDC (Genomic Data Commons) harvester — NCI cancer projects.

L0 (Public) metadata only — controlled-access 데이터 파일은 v1 범위 제외 (마스터 플랜 §9.3).

검증 출처 (docs/external-apis.md §8, 직접 호출 2026-05-06):
- Base: https://api.gdc.cancer.gov/
- /projects?from=N&size=N&expand=summary.experimental_strategies,program — pagination
- 91 total projects (TCGA, TARGET, GENIE, HCMI, FM-AD ...)
- 각 project: project_id, name, primary_site (cancer organs), disease_type (cancer types),
  summary.case_count, summary.experimental_strategies (RNA-Seq/WGS/WXS/...)

GDC 모든 project 는 Homo sapiens — organism_taxid 항상 [9606].
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
from .geo import _RETRY_POLICY

logger = logging.getLogger(__name__)

GDC_BASE = "https://api.gdc.cancer.gov/"
PAGE_SIZE = 50
DEFAULT_TIMEOUT_S = 30.0
EXPAND = "summary,summary.experimental_strategies,program"


class GdcHarvester(Harvester):
    source_db = "GDC"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rps: float = 5.0,
    ) -> None:
        self._min_interval_s = 1.0 / rps
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client = client or httpx.AsyncClient(
            base_url=GDC_BASE, timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": "OmicsPlorer/0.1.0"},
        )
        self._cache: dict[str, dict[str, Any]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GdcHarvester:
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

    async def _get_json(self, path: str, params: dict | None = None) -> dict:
        async for attempt in AsyncRetrying(**_RETRY_POLICY):
            with attempt:
                await self._throttle()
                resp = await self._client.get(path, params=params)
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError("unreachable")

    async def list_updated_since(self, since: datetime) -> AsyncIterator[str]:
        """모든 GDC project_id 를 yield. since 필터는 GDC API 가 직접 지원하지 않음 — v1 무필터."""
        from_offset = 0
        total: int | None = None
        while True:
            payload = await self._get_json(
                "/projects",
                params={"from": str(from_offset), "size": str(PAGE_SIZE), "expand": EXPAND},
            )
            data = payload.get("data") or {}
            hits = data.get("hits") or []
            if total is None:
                total = (data.get("pagination") or {}).get("total") or 0
                logger.info("gdc projects total=%d", total)
            for h in hits:
                pid = h.get("project_id") or h.get("id")
                if pid:
                    self._cache[pid] = h
                    yield pid
            from_offset += len(hits)
            if not hits or from_offset >= total:
                break

    async def fetch_raw(self, source_id: str) -> dict:
        cached = self._cache.get(source_id)
        if cached is not None:
            return {"project": cached}
        payload = await self._get_json(f"/projects/{source_id}", params={"expand": EXPAND})
        return {"project": (payload.get("data") or {})}
