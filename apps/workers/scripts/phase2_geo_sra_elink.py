"""Phase 2 — GEO → SRA cross-reference augmentation via NCBI EUtils elink.

V2 개선 (2026-05-28):
  - **Incremental INSERT**: 배치마다 즉시 DB 인서트 (중단 시 손실 0)
  - **Retry with backoff**: elink/esummary 실패 시 1s/2s/4s 재시도 (502/chunked-read 회복)
  - **Checkpoint**: 100 배치마다 진행 상태 저장
  - **Resume safe**: WHERE NOT EXISTS 가 이미 처리된 GEO 자동 skip

처리:
  1. Load targets: source_db='GEO' + gdstype sequencing/HTS + SRA cross-ref 없음
  2. For each batch of 20:
     a. elink (retry 3x) → SRA UIDs
     b. esummary (retry 3x) → SRP accession
     c. INSERT dataset_sources 즉시
     d. 100 배치마다 checkpoint 저장
  3. 종료: 리포트 출력

총 소요: 약 5-7시간 (네트워크 안정 시).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import time
from pathlib import Path

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHECKPOINT_PATH = Path("/tmp/genofinder-phase2-checkpoint.json")
REPORT_PATH = Path("/tmp/genofinder-phase2-report.json")
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ELINK_BATCH = 20
ESUMMARY_BATCH = 200
RETRY_DELAYS = [1, 2, 4]  # exponential backoff
CHECKPOINT_EVERY = 100

# Graceful shutdown
_should_stop = False


def _signal_handler(signum, frame):
    global _should_stop
    _should_stop = True
    log.warning("SIGNAL %s — graceful stop", signum)


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def _pg_dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _load_checkpoint() -> dict:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except json.JSONDecodeError:
            log.warning("checkpoint corrupt — starting fresh")
    return {
        "batches_done": 0,
        "elink_calls": 0,
        "elink_failures": 0,
        "esummary_calls": 0,
        "esummary_failures": 0,
        "geos_mapped": 0,
        "inserts_done": 0,
        "started_at": time.time(),
    }


def _save_checkpoint(state: dict) -> None:
    CHECKPOINT_PATH.write_text(json.dumps(state, indent=2))


async def load_targets(conn: asyncpg.Connection) -> list[dict]:
    log.info("loading sequencing GEO with missing SRA cross-ref…")
    rows = await conn.fetch(
        """
        SELECT
          d.id::text AS dataset_id,
          d.source_id,
          (d.raw_metadata->'result'->'uids'->>0) AS geo_uid
        FROM datasets d
        WHERE d.source_db = 'GEO'
          AND (
            d.raw_metadata->'result'->(d.raw_metadata->'result'->'uids'->>0)->>'gdstype' LIKE '%sequencing%'
            OR d.raw_metadata->'result'->(d.raw_metadata->'result'->'uids'->>0)->>'gdstype' LIKE '%HTS%'
          )
          AND NOT EXISTS (
            SELECT 1 FROM dataset_sources ds
            WHERE ds.dataset_id = d.id AND ds.source_db = 'SRA'
          )
        """
    )
    log.info("  %d targets loaded (이미 SRA cross-ref 있는 것 자동 제외)", len(rows))
    return [dict(r) for r in rows]


class NcbiClient:
    def __init__(self, api_key: str | None, rps: float):
        self._key = api_key
        self._min_interval = 1.0 / rps
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=60.0,
            headers={"User-Agent": "OmicsPlorer/1.0 (research)"},
        )

    async def _throttle(self):
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            wait = max(0.0, self._next_at - now)
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_at = max(now, self._next_at) + self._min_interval

    async def get(self, path: str, params):
        if self._key:
            if isinstance(params, dict):
                params = {**params, "api_key": self._key}
            else:
                params = list(params) + [("api_key", self._key)]
        await self._throttle()
        resp = await self._client.get(f"{EUTILS_BASE}/{path}", params=params)
        resp.raise_for_status()
        return resp

    async def close(self):
        await self._client.aclose()


async def elink_with_retry(
    ncbi: NcbiClient, geo_uids: list[str]
) -> dict[str, list[str]]:
    """GEO UIDs → {geo_uid: [sra_uids]}. 실패 시 backoff retry."""
    params = [("dbfrom", "gds"), ("db", "sra"), ("retmode", "json")] + [
        ("id", u) for u in geo_uids
    ]
    last_err = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            resp = await ncbi.get("elink.fcgi", params)
            data = resp.json()
            out: dict[str, list[str]] = {}
            for ls in data.get("linksets", []):
                source_ids = ls.get("ids") or []
                if not source_ids:
                    continue
                source_id = str(source_ids[0])
                sra_uids: list[str] = []
                for db in ls.get("linksetdbs") or []:
                    if db.get("linkname") in ("gds_sra", "gds_sra_all"):
                        sra_uids.extend(str(x) for x in (db.get("links") or []))
                if sra_uids:
                    out[source_id] = list(set(sra_uids))
            return out
        except Exception as e:
            last_err = e
            log.debug("  elink attempt %d failed: %s", attempt + 1, e)
    log.warning("elink failed permanently for batch %d uids: %s", len(geo_uids), last_err)
    return {}


async def esummary_sra_with_retry(
    ncbi: NcbiClient, sra_uids: list[str]
) -> dict[str, str]:
    """SRA UIDs → {sra_uid: SRP/ERP/DRP accession}."""
    if not sra_uids:
        return {}
    last_err = None
    for attempt, delay in enumerate([0] + RETRY_DELAYS):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            resp = await ncbi.get(
                "esummary.fcgi",
                {"db": "sra", "id": ",".join(sra_uids), "retmode": "json"},
            )
            data = resp.json()
            result = data.get("result", {})
            out: dict[str, str] = {}
            for uid in result.get("uids") or []:
                rec = result.get(str(uid)) or {}
                expxml = rec.get("expxml") or ""
                m_study = re.search(r'<Study\s+acc="([^"]+)"', expxml)
                if m_study and m_study.group(1).startswith(("SRP", "ERP", "DRP")):
                    out[str(uid)] = m_study.group(1)
            return out
        except Exception as e:
            last_err = e
            log.debug("  esummary attempt %d failed: %s", attempt + 1, e)
    log.warning("esummary failed permanently for batch %d: %s", len(sra_uids), last_err)
    return {}


async def main() -> None:
    t0 = time.perf_counter()
    log.info("Phase 2 v2 — GEO→SRA elink (incremental insert, retry, checkpoint)")
    api_key = os.environ.get("NCBI_EUTILS_API_KEY")
    rps = 10.0 if api_key else 3.0
    log.info("  rate limit: %.1f rps (api_key=%s)", rps, bool(api_key))

    state = _load_checkpoint()
    if state.get("batches_done", 0) > 0:
        log.info(
            "  resuming: batches_done=%d, inserts=%d",
            state["batches_done"], state["inserts_done"],
        )

    pg_conn = await asyncpg.connect(_pg_dsn())
    try:
        targets = await load_targets(pg_conn)
    except Exception:
        await pg_conn.close()
        raise

    ncbi = NcbiClient(api_key, rps)

    # 시작 offset (체크포인트 reset 가능)
    start_batch = state.get("batches_done", 0)
    start_offset = start_batch * ELINK_BATCH
    if start_offset >= len(targets):
        log.info("  체크포인트가 데이터 길이 초과 → 처음부터")
        start_offset = 0
        start_batch = 0
    log.info("  start_offset=%d (batch %d/%d)", start_offset, start_batch, len(targets) // ELINK_BATCH + 1)

    log.info("step 1 — incremental elink + esummary + INSERT (batch_elink=%d, batch_esum=%d)",
             ELINK_BATCH, ESUMMARY_BATCH)

    try:
        for i in range(start_offset, len(targets), ELINK_BATCH):
            if _should_stop:
                log.info("  stop signal — checkpoint 저장 후 종료")
                break

            batch = targets[i : i + ELINK_BATCH]
            dataset_id_by_geo_uid = {t["geo_uid"]: t["dataset_id"] for t in batch if t["geo_uid"]}
            geo_uids = list(dataset_id_by_geo_uid.keys())
            if not geo_uids:
                continue

            # elink
            state["elink_calls"] += 1
            geo_to_sra_uids = await elink_with_retry(ncbi, geo_uids)
            if not geo_to_sra_uids:
                state["elink_failures"] += 1
                state["batches_done"] += 1
                continue

            # 모든 SRA UID 모아서 esummary 한 번에
            all_sra_uids = set()
            for ss in geo_to_sra_uids.values():
                all_sra_uids.update(ss)

            # esummary chunked
            sra_to_acc: dict[str, str] = {}
            sra_uid_list = list(all_sra_uids)
            for j in range(0, len(sra_uid_list), ESUMMARY_BATCH):
                state["esummary_calls"] += 1
                chunk = sra_uid_list[j : j + ESUMMARY_BATCH]
                result = await esummary_sra_with_retry(ncbi, chunk)
                if not result:
                    state["esummary_failures"] += 1
                sra_to_acc.update(result)

            # build insert tuples (dedupe at study level per GEO)
            inserts: list[tuple] = []
            geos_with_match = 0
            for geo_uid, sra_uids in geo_to_sra_uids.items():
                dataset_id = dataset_id_by_geo_uid.get(geo_uid)
                if not dataset_id:
                    continue
                accs = {sra_to_acc[u] for u in sra_uids if u in sra_to_acc}
                if accs:
                    geos_with_match += 1
                for acc in accs:
                    inserts.append((
                        dataset_id, "SRA", acc,
                        f"https://www.ncbi.nlm.nih.gov/sra/?term={acc}",
                        False, "elink",
                    ))

            # INSERT immediately
            if inserts:
                try:
                    await pg_conn.executemany(
                        """
                        INSERT INTO dataset_sources
                          (dataset_id, source_db, source_id, raw_url, is_primary, linked_via)
                        VALUES ($1::uuid, $2, $3, $4, $5, $6)
                        ON CONFLICT (dataset_id, source_db, source_id) DO NOTHING
                        """,
                        inserts,
                    )
                    state["inserts_done"] += len(inserts)
                    state["geos_mapped"] += geos_with_match
                except Exception as e:
                    log.warning("INSERT failed for batch: %s", e)

            state["batches_done"] += 1

            # progress log + checkpoint
            if state["batches_done"] % CHECKPOINT_EVERY == 0:
                elapsed = time.time() - state["started_at"]
                rate = state["batches_done"] / (elapsed / 60) if elapsed > 0 else 0
                pct = 100.0 * (i + ELINK_BATCH) / len(targets)
                log.info(
                    "  %d/%d (%.1f%%) | elink=%d (fail %d) | esum=%d (fail %d) | geos=%d | inserts=%d | %.1f batch/min",
                    i + ELINK_BATCH, len(targets), pct,
                    state["elink_calls"], state["elink_failures"],
                    state["esummary_calls"], state["esummary_failures"],
                    state["geos_mapped"], state["inserts_done"], rate,
                )
                _save_checkpoint(state)

    finally:
        await pg_conn.close()
        await ncbi.close()
        _save_checkpoint(state)

        elapsed = time.perf_counter() - t0
        report = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "elapsed_s": round(elapsed, 1),
            "targets_total": len(targets),
            **state,
        }
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

        log.info("=" * 60)
        if _should_stop:
            log.info("⏸  Phase 2 paused at batch %d", state["batches_done"])
        else:
            log.info("✅ Phase 2 complete in %.0fs", elapsed)
        log.info("  batches done       : %d", state["batches_done"])
        log.info("  elink calls/fail   : %d / %d", state["elink_calls"], state["elink_failures"])
        log.info("  esummary calls/fail: %d / %d", state["esummary_calls"], state["esummary_failures"])
        log.info("  GEOs got SRA       : %d", state["geos_mapped"])
        log.info("  dataset_sources INSERTed: %d", state["inserts_done"])
        log.info("  report → %s", REPORT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
