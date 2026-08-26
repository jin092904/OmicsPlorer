"""GEO Series Matrix harvester — sample-level characteristics.

마스터 플랜 §5 의 sample-level fetcher. 본 모듈은 study-level GeoHarvester 와 별개로
GEO 의 Series Matrix file(`*_series_matrix.txt.gz`) 에서 per-sample characteristics 를
파싱한다.

L0(Public) 데이터만 다루므로 §12 보안 control 미적용.

검증 출처:
- Series Matrix file 위치: NCBI FTP
    https://ftp.ncbi.nlm.nih.gov/geo/series/GSExxxnnn/<GSE_ID>/matrix/<GSE_ID>_series_matrix.txt.gz
  여기서 GSExxxnnn 은 GSE ID 의 마지막 3자리를 'nnn' 으로 치환한 stub (예: GSE176178 → GSE176nnn).
- 파일 포맷 (텍스트, gzip):
    !Series_<...>  : study-level
    !Sample_<...>  : sample-level (탭으로 GSM 별 컬럼)
    !Sample_geo_accession\t"GSM..."\t"GSM..."...
    !Sample_characteristics_ch1\t"sex: male"\t"sex: female"...   (여러 줄 가능)

본 모듈이 추출하는 항목:
    Sample_geo_accession    → source_sample_id
    Sample_characteristics_ch1 의 'sex: ...', 'age: ...', 'disease state: ...',
                                'treatment: ...' 등 key:value 쌍

설계:
- 비동기 httpx 다운로드 → gzip 디코드 → 텍스트 파싱 (메모리). 파일 크기는 GSE 당
  보통 수십 KB~수 MB — 단일 머신 환경에서 메모리 보관 가능. 매우 큰 GSE (>10MB) 는
  fail-open 으로 처리 (parse 실패 시 빈 결과 반환, indexer 가 skip).
- rate limit 은 NCBI FTP 기준 별도 정책 없음 — 보수적으로 GeoHarvester 와 같은
  3 rps 토큰 버킷 사용.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import re
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

NCBI_FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/geo/series/"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_RPS = 3.0
MAX_BYTES = 50 * 1024 * 1024  # 50MB hard cap — 매우 큰 GSE 는 skip

_GSE_RE = re.compile(r"^GSE(\d+)$")

# Sample_characteristics_ch1 의 'key: value' 패턴.
# value 는 ';' 또는 ',' 로 분리되는 경우도 있으나 일단 single key:value 만 지원 — v1 단순화.
_CHAR_KV_RE = re.compile(r"^\s*([^:]+?)\s*:\s*(.+?)\s*$")

# 정규화 사전 — 입력의 다양성을 canonical 값으로 매핑.
_SEX_NORM: dict[str, str] = {
    "m": "male", "male": "male", "man": "male", "boy": "male",
    "남": "male", "남성": "male",
    "f": "female", "female": "female", "woman": "female", "girl": "female",
    "여": "female", "여성": "female",
}
# Sample_characteristics_ch1 에서 'sex' 와 비슷한 의미로 사용되는 키들.
_SEX_KEYS = {"sex", "gender"}
_AGE_KEYS = {"age", "age (years)", "age_years", "age_year", "age at diagnosis", "age_at_diagnosis"}
# 'sample group', 'response', 'response status', 'responder', 'response group' 추가 —
# drug response study (R/NR) 에서 자주 쓰이는 라벨 키. UI 의 "진단/그룹 라벨" 컬럼이
# 그룹 비교를 명확히 보여주도록.
_DISEASE_KEYS = {
    "disease state", "disease_state", "diagnosis", "condition", "phenotype", "group",
    "sample group", "response", "response status", "responder", "response group",
    "patient group", "cohort", "arm", "study arm",
}
_TREATMENT_KEYS = {"treatment", "drug", "intervention", "agent", "therapy"}


class GeoMatrixHarvester:
    """Series Matrix file → list[dict] (sample characteristics).

    호출자는 GSE accession 을 넘기고, sample dict 리스트를 받는다. 각 dict 는:
        {
            "source_sample_id": "GSM...",
            "sex": "male" | "female" | None,
            "age_value": float | None,
            "age_unit": "year" | "month" | "day" | None,
            "disease_state": str | None,
            "treatment": str | None,
            "raw_attributes": {<key>: <value>, ...},  # 전체 characteristics dict
        }
    """

    source_db = "GEO"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        rps: float = DEFAULT_RPS,
    ) -> None:
        self._min_interval_s = 1.0 / rps
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client = client or httpx.AsyncClient(
            base_url=NCBI_FTP_BASE,
            timeout=DEFAULT_TIMEOUT_S,
            headers={"User-Agent": "OmicsPlorer/0.1.0 (https://github.com/jin092904/OmicsPlorer)"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GeoMatrixHarvester":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _rate_limit(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next_at:
                await asyncio.sleep(self._next_at - now)
                now = loop.time()
            self._next_at = now + self._min_interval_s

    def _matrix_url(self, gse: str) -> str:
        m = _GSE_RE.match(gse)
        if not m:
            raise ValueError(f"invalid GSE accession: {gse!r}")
        digits = m.group(1)
        # nnn stub: 마지막 3자리를 'nnn' 으로. GSE9 → GSEnnn, GSE176178 → GSE176nnn.
        if len(digits) <= 3:
            stub = "GSEnnn"
        else:
            stub = f"GSE{digits[:-3]}nnn"
        return f"{stub}/{gse}/matrix/{gse}_series_matrix.txt.gz"

    async def fetch_samples(self, gse: str) -> list[dict[str, Any]]:
        """GSE → sample dict 리스트. 파일이 없거나 파싱 실패 시 빈 리스트.

        네트워크 에러는 tenacity 로 재시도 (네트워크 / 5xx). 404 는 즉시 빈 리스트.
        """
        url = self._matrix_url(gse)
        await self._rate_limit()

        def _is_retriable(exc: BaseException) -> bool:
            if isinstance(exc, httpx.HTTPStatusError):
                return 500 <= exc.response.status_code < 600
            return isinstance(exc, (httpx.NetworkError, httpx.TimeoutException))

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1.0, min=1.0, max=10.0),
                retry=retry_if_exception(_is_retriable),
                reraise=True,
            ):
                with attempt:
                    resp = await self._client.get(url)
                    if resp.status_code == 404:
                        logger.info("GEO matrix not found for %s", gse)
                        return []
                    resp.raise_for_status()
                    raw = resp.content
        except Exception as e:
            logger.warning("GEO matrix fetch failed for %s: %s", gse, type(e).__name__)
            return []

        if len(raw) > MAX_BYTES:
            logger.warning("GEO matrix %s too large (%d bytes) — skip", gse, len(raw))
            return []

        try:
            text = gzip.decompress(raw).decode("utf-8", errors="replace")
        except (OSError, EOFError) as e:
            logger.warning("GEO matrix %s gzip decode failed: %s", gse, type(e).__name__)
            return []

        return parse_series_matrix(text)


# ---------------------------------------------------------------------------
# pure parsing — testable without network
# ---------------------------------------------------------------------------


def parse_series_matrix(text: str) -> list[dict[str, Any]]:
    """Series Matrix 텍스트 → sample dict 리스트.

    파싱 규칙:
    - `!Sample_geo_accession` 라인이 GSM 컬럼 순서를 정한다.
    - `!Sample_characteristics_ch1` 가 여러 줄일 수 있다 — 각 줄이 'key: value' 의
      한 컬럼씩을 갖는다. 같은 GSM 의 여러 characteristics 는 raw_attributes 에 merge.
    - 그 외 모든 !Sample_<field> 도 raw_attributes 에 보존 (예: Sample_title).
    """
    gsms: list[str] = []
    raw_attrs_per_gsm: list[dict[str, str]] = []

    for line in text.splitlines():
        if not line.startswith("!Sample_"):
            continue
        try:
            key, rest = line[1:].split("\t", 1)
        except ValueError:
            continue
        values = _split_tabbed(rest)

        if key == "Sample_geo_accession":
            gsms = values
            raw_attrs_per_gsm = [{} for _ in gsms]
        elif key == "Sample_characteristics_ch1":
            # 'key: value' 패턴 추출 — 각 컬럼이 한 sample 의 한 characteristic.
            if not gsms:
                continue
            for i, val in enumerate(values):
                if i >= len(raw_attrs_per_gsm):
                    break
                ck, cv = _parse_kv(val)
                if ck is None or cv is None:
                    continue
                # 중복 키는 ';' join 으로 보존 (드물게 같은 key 가 여러 번 등장)
                existing = raw_attrs_per_gsm[i].get(ck)
                if existing is None:
                    raw_attrs_per_gsm[i][ck] = cv
                else:
                    raw_attrs_per_gsm[i][ck] = f"{existing}; {cv}"
        else:
            # 그 외 Sample_* 도 raw 에 보존 (key=field, value=원본 컬럼).
            if not gsms:
                continue
            for i, val in enumerate(values):
                if i >= len(raw_attrs_per_gsm):
                    break
                # 비어있지 않은 값만 저장 — 비교적 흔한 필드 (Sample_title) 위주.
                if val:
                    raw_attrs_per_gsm[i].setdefault(key, val)

    return [
        _build_sample_record(gsm, raw)
        for gsm, raw in zip(gsms, raw_attrs_per_gsm)
    ]


def _split_tabbed(rest: str) -> list[str]:
    """탭 구분 + 양 끝 따옴표 제거."""
    parts = rest.rstrip("\n").split("\t")
    out = []
    for p in parts:
        p = p.strip()
        if p.startswith('"') and p.endswith('"') and len(p) >= 2:
            p = p[1:-1]
        out.append(p)
    return out


def _parse_kv(value: str) -> tuple[str | None, str | None]:
    """'sex: female' → ('sex', 'female'). 매칭 안 되면 (None, None)."""
    if not value:
        return None, None
    m = _CHAR_KV_RE.match(value)
    if not m:
        return None, None
    return m.group(1).lower(), m.group(2)


def _build_sample_record(gsm: str, raw: dict[str, str]) -> dict[str, Any]:
    """raw_attributes dict → indexer 가 그대로 UPSERT 할 수 있는 sample dict."""
    sex = _normalize_sex(_pick(raw, _SEX_KEYS))
    age_value, age_unit = _normalize_age(_pick(raw, _AGE_KEYS))
    disease_state = _pick(raw, _DISEASE_KEYS)
    treatment = _pick(raw, _TREATMENT_KEYS)
    return {
        "source_sample_id": gsm,
        "sex": sex,
        "age_value": age_value,
        "age_unit": age_unit,
        "disease_state": disease_state,
        "treatment": treatment,
        "raw_attributes": raw,
    }


def _pick(raw: dict[str, str], keys: set[str]) -> str | None:
    """raw 의 키 중 첫 매칭. 키 비교는 lowercase exact."""
    for k, v in raw.items():
        if k in keys and v:
            return v
    return None


def _normalize_sex(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    return _SEX_NORM.get(v)


_AGE_NUM_RE = re.compile(r"-?\d+(\.\d+)?")


def _normalize_age(value: str | None) -> tuple[float | None, str | None]:
    """'45 years' → (45.0, 'year'). '6 months' → (6.0, 'month'). 'unknown' → (None, None)."""
    if not value:
        return None, None
    v = value.strip().lower()
    if v in {"unknown", "n/a", "na", "nd", "not available", "not provided"}:
        return None, None
    # 범위 형태 '18-25' → 중간값 21.5
    range_m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)", v)
    if range_m:
        lo = float(range_m.group(1))
        hi = float(range_m.group(2))
        num: float | None = (lo + hi) / 2.0
        rest = v[range_m.end():]
    else:
        num_m = _AGE_NUM_RE.search(v)
        num = float(num_m.group(0)) if num_m else None
        rest = v[num_m.end():] if num_m else v
    if num is None:
        return None, None
    unit = "year"
    if "month" in rest or "mo" == rest.strip() or rest.strip().startswith("mo"):
        unit = "month"
    elif "day" in rest or rest.strip() == "d":
        unit = "day"
    elif "week" in rest or "wk" in rest:
        # week → day (×7) — 정규화 결정 (DB enum 단순화)
        num *= 7.0
        unit = "day"
    return num, unit
