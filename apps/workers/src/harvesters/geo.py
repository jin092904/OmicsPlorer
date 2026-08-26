"""GEO harvester — NCBI E-utilities (gds 데이터베이스).

본 harvester 는 L0 (Public) 데이터만 다룬다. 따라서 §12 보안 control(envelope encryption,
RLS, redaction 등)은 적용되지 않는다 — 코드 단에서 사용자 쿼리·tenant 데이터를 절대 참조하지 않는다.

마스터 플랜:
- §5.1 Harvester 공통 인터페이스
- §5.5 멱등성: 같은 source_id 에 대해 UPSERT (이는 indexer 레이어에서 처리)

검증 출처 (docs/external-apis.md §1):
- Base URL: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
- Rate limit: 3 rps (no key), 10 rps (with NCBI_EUTILS_API_KEY)
- 인코딩: 공백 → '+', '"' → '%22', '#' → '%23'

NCBI gds 데이터베이스 메모 (직접 검증, 2026-05-06):
- UID 의 첫 자리로 record type 구분 — Series(GSE) UID 는 '2' 로 시작.
- 날짜 필터는 **`datetype=pdat` (publication date) 만 동작**. `mdat`/`edat` 는 gds 에서 No items found 반환.
- esearch?db=gds&term=gse[ETYP]&datetype=pdat&mindate=YYYY/MM/DD&maxdate=YYYY/MM/DD&retmode=json
- esummary?db=gds&id=<uid>&retmode=json&version=2.0 → 본 harvester 가 반환하는 raw payload
- 응답 구조: {"result": {"uids": [...], "<uid>": {...}}}
- 레코드 키 (모두 소문자, 직접 검증): uid, accession, gds, title, summary, gpl, gse,
  taxon, entrytype, gdstype, ptechtype, valtype, ssinfo, subsetinfo, pdat, suppfile,
  samples, relations, extrelations, n_samples
- 즉, 인덱서는 raw["result"][uid]["accession"] (소문자) 로 GSE accession 을 가져온다.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from .base import Harvester

logger = logging.getLogger(__name__)

NCBI_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DB_NAME = "gds"
ESEARCH_PAGE_SIZE = 500  # NCBI 권장 retmax (TODO(verify): 1차 출처에서 한도 재확인)
ESUMMARY_BATCH_SIZE = 200  # esummary 는 batch ID 지원
DEFAULT_TIMEOUT_S = 30.0


class GeoHarvester(Harvester):
    """GEO Series (GSE) records via NCBI E-utilities."""

    source_db = "GEO"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        rps: float | None = None,
    ) -> None:
        # api_key 가 있으면 10 rps, 없으면 3 rps (NCBI 정책 — docs/external-apis.md §1).
        self._api_key = api_key or os.environ.get("NCBI_EUTILS_API_KEY")
        target_rps = rps if rps is not None else (10.0 if self._api_key else 3.0)
        self._min_interval_s = 1.0 / target_rps
        self._next_at = 0.0  # monotonic deadline
        self._lock = asyncio.Lock()
        self._client = client or httpx.AsyncClient(
            base_url=NCBI_EUTILS_BASE,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": "OmicsPlorer/0.1.0 (https://github.com/jin092904/OmicsPlorer)"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GeoHarvester:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ---- public ----

    async def list_updated_since(self, since: datetime) -> AsyncIterator[str]:
        """Yield NCBI UIDs of GEO Series (GSE) records published since `since`.

        구현 상세:
            - GEO gds 는 mdat 가 아닌 **pdat** 기반 (직접 검증).
            - esearch 는 한 번에 retmax 만큼 결과를 반환하고, 추가는 retstart 로 페이지네이션.
            - 멱등성: 같은 since 에 대해 동일 UID 집합 (NCBI 가 retroactive 로 변경하지 않는 한).
            - filter: 'gse[ETYP]' 로 Series 만 필터링 (Sample/Platform 제외).
        """
        mindate = since.strftime("%Y/%m/%d")
        maxdate = datetime.now().strftime("%Y/%m/%d")

        retstart = 0
        total = -1
        while True:
            params = self._auth_params({
                "db": DB_NAME,
                "term": "gse[ETYP]",
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
                    "esearch: total=%d window=%s..%s",
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
        """Return esummary payload for a single GEO uid.

        반환값은 NCBI esummary 의 원본 JSON 을 그대로 보존한다 — datasets.raw_metadata 에 그대로 저장.
        가공·정규화는 별도 extractor 에서 수행 (LLM 구조화 단계).
        """
        params = self._auth_params({
            "db": DB_NAME,
            "id": source_id,
            "retmode": "json",
            "version": "2.0",
        })
        payload = await self._get_json("esummary.fcgi", params)
        result = payload.get("result") or {}
        if source_id not in result:
            raise ValueError(f"GEO uid {source_id!r} not found in esummary response")
        return payload

    async def _get_json(self, path: str, params: dict[str, str]) -> dict:
        """Throttle + retry 한 GET. 429/5xx/network 오류는 exponential backoff 로 재시도."""
        async for attempt in AsyncRetrying(**_RETRY_POLICY):
            with attempt:
                await self._throttle()
                resp = await self._client.get(path, params=params)
                resp.raise_for_status()
                return resp.json()
        raise RuntimeError("unreachable — AsyncRetrying always exits via with attempt")

    # ---- internals ----

    def _auth_params(self, base: dict[str, str]) -> dict[str, str]:
        """api_key 가 있으면 10 rps tier 를 사용하도록 파라미터에 부착."""
        if self._api_key:
            return {**base, "api_key": self._api_key}
        return base

    async def _throttle(self) -> None:
        """단일 process 내 token bucket — 초당 호출 수 제한."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = max(0.0, self._next_at - now)
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = max(now, self._next_at) + self._min_interval_s


def _is_retriable_http(exc: BaseException) -> bool:
    """429 / 5xx / connect 오류만 재시도."""
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


_RETRY_POLICY = dict(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception(_is_retriable_http),
    reraise=True,
)
