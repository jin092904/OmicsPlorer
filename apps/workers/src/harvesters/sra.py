"""SRA harvester — NCBI E-utilities (sra 데이터베이스).

L0 (Public) 데이터만 다룬다 — §12 보안 control 미적용.

검증 출처 (docs/external-apis.md §1, NCBI 직접 호출 2026-05-06):
- Base URL: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
- Date filter: pdat (publication date) — gds/sra 모두 동일하게 작동
- esearch 응답: idlist 의 UID 는 SRA 내부 ID
- esummary 응답: result[uid] 안에 expxml (XML 문자열로 임베딩) + runs + createdate

esummary expxml 안의 element (직접 검증):
    <Summary><Title>...<Platform instrument_model="...">...
    <Submitter acc="SRA######">
    <Experiment acc="SRX######">
    <Study acc="SRP######" name="...">
    <Organism taxid="9606" ScientificName="...">
    <Library_descriptor><LIBRARY_STRATEGY/> <LIBRARY_SOURCE/> ...
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
from tenacity import AsyncRetrying

from .base import Harvester
from .geo import _RETRY_POLICY  # 공용 retry policy 재사용

logger = logging.getLogger(__name__)

NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DB_NAME = "sra"
ESEARCH_PAGE_SIZE = 500
DEFAULT_TIMEOUT_S = 30.0


class SraHarvester(Harvester):
    """SRA experiment records via NCBI E-utilities.

    Indexing semantics (v0): yields experiment-level UIDs, indexer aggregates
    by study accession (SRP######). Multiple experiments in the same study
    UPSERT to the same datasets row.
    """

    source_db = "SRA"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        rps: float | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("NCBI_EUTILS_API_KEY")
        target_rps = rps if rps is not None else (10.0 if self._api_key else 3.0)
        self._min_interval_s = 1.0 / target_rps
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client = client or httpx.AsyncClient(
            base_url=NCBI_EUTILS_BASE,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": "OmicsPlorer/0.1.0 (https://github.com/jin092904/OmicsPlorer)"},
        )

    async def _throttle(self) -> None:
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = max(0.0, self._next_at - now)
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = max(now, self._next_at) + self._min_interval_s

    async def _get_json(self, path: str, params: dict[str, str]) -> dict:
        async for attempt in AsyncRetrying(**_RETRY_POLICY):
            with attempt:
                await self._throttle()
                resp = await self._client.get(path, params=params)
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError("unreachable")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SraHarvester:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def list_updated_since(self, since: datetime) -> AsyncIterator[str]:
        """Yield SRA experiment UIDs published since `since`."""
        mindate = since.strftime("%Y/%m/%d")
        maxdate = datetime.now().strftime("%Y/%m/%d")

        retstart = 0
        total = -1
        while True:
            params = self._auth_params({
                "db": DB_NAME,
                # 모든 strategy/organism 포함 — 필터는 indexer 가 결정
                "term": "all[FILT]",
                "datetype": "pdat",
                "mindate": mindate,
                "maxdate": maxdate,
                "retmode": "json",
                "retmax": str(ESEARCH_PAGE_SIZE),
                "retstart": str(retstart),
            })
            payload = await self._get_json("esearch.fcgi", params)
            esr = payload.get("esearchresult") or {}
            ids: list[str] = esr.get("idlist") or []
            if total < 0:
                total = int(esr.get("count", 0))
                logger.info(
                    "esearch sra: total=%d window=%s..%s",
                    total, mindate, maxdate,
                )
            if not ids:
                return
            for uid in ids:
                yield uid
            retstart += len(ids)
            if retstart >= total:
                return

    async def fetch_raw(self, source_id: str) -> dict:
        """SRA esummary payload for a single uid."""
        params = self._auth_params({
            "db": DB_NAME,
            "id": source_id,
            "retmode": "json",
            "version": "2.0",
        })
        payload = await self._get_json("esummary.fcgi", params)
        result = payload.get("result") or {}
        if source_id not in result:
            raise ValueError(f"SRA uid {source_id!r} not found in esummary response")
        return payload

    def _auth_params(self, base: dict[str, str]) -> dict[str, str]:
        if self._api_key:
            return {**base, "api_key": self._api_key}
        return base
