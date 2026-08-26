"""대규모 GEO ingest — Week 2 검증 기준 (1만 GSE).

- 시간창 90 일, 한도 10000 (인자로 변경 가능)
- API key 있으면 10 rps, 없으면 3 rps (harvester 가 자동 throttle)
- 100 records 단위로 transaction commit — 긴 tx 회피

LLM 추출은 본 스크립트 범위 외 (extraction_version=v0-stub 으로 들어감).
완료 후 reindex_all_search_layers 호출하여 Qdrant + OpenSearch 동기화.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.db import get_engine
from src.harvesters.geo import GeoHarvester
from src.indexer.geo import index_geo_record
from src.indexer.pipeline import collect_uids, reindex_all_search_layers


async def harvest(days: int = 90, max_records: int = 10000, batch_commit: int = 100) -> None:
    eng = get_engine()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"window: since={since.isoformat()} (last {days}d), max={max_records}")

    t0 = time.perf_counter()
    async with GeoHarvester() as h:
        # esearch 페이지네이션은 harvester 가 처리. collect_uids 가 max 까지 수집.
        uids = await collect_uids(h, since, max_records)
        t_search = time.perf_counter() - t0
        print(f"esearch: {len(uids)} UIDs in {t_search:.1f}s")

        # 병렬 fetch — NCBI 레이턴시(~200ms/call)로 sequential 시 2-3rps 머무름.
        # harvester 의 _throttle 이 토큰버킷 역할을 하므로 동시 N개 실행해도 총 rate ≤ 10 rps.
        concurrency = 12
        sem = asyncio.Semaphore(concurrency)

        async def _one(uid: str) -> tuple[str, dict | None, str | None]:
            async with sem:
                try:
                    return uid, await h.fetch_raw(uid), None
                except Exception as e:
                    return uid, None, f"{type(e).__name__}: {str(e)[:80]}"

        inserted = 0
        skipped = 0
        i = 0
        while i < len(uids):
            chunk = uids[i : i + batch_commit]
            # 병렬 fetch 먼저, 그 후 모든 payload 를 한 트랜잭션에 INSERT
            results = await asyncio.gather(*(_one(u) for u in chunk))
            async with eng.connect() as conn:
                async with conn.begin():
                    for uid, payload, err in results:
                        if err is not None or payload is None:
                            skipped += 1
                            if skipped <= 5:
                                print(f"  skip uid={uid}: {err}")
                            continue
                        try:
                            await index_geo_record(conn, payload, uid)
                            inserted += 1
                        except Exception as e:
                            skipped += 1
                            if skipped <= 5:
                                print(f"  index fail uid={uid}: {type(e).__name__}: {str(e)[:80]}")
            i += len(chunk)
            elapsed = time.perf_counter() - t0
            rps = inserted / elapsed if elapsed > 0 else 0
            print(f"  progress: {i}/{len(uids)} | inserted={inserted} skipped={skipped} | "
                  f"elapsed={elapsed:.0f}s | {rps:.1f} rps")

    t_harvest = time.perf_counter() - t0
    print(f"\nharvest finished: inserted={inserted} skipped={skipped} in {t_harvest:.0f}s")

    # DB count 확인
    async with eng.connect() as conn:
        result = await conn.execute(text("SELECT count(*) FROM datasets WHERE source_db='GEO'"))
        total = result.scalar()
    print(f"datasets table GEO count: {total}")

    # Reindex (LLM extraction 은 별도 PR 에서. 본 단계는 모달리티 빈 채로도 OK)
    t1 = time.perf_counter()
    print("reindexing search layers (this re-embeds all records, takes ~30-60s/1k)...")
    stats = await reindex_all_search_layers(eng)
    print(f"reindex: {stats} in {time.perf_counter() - t1:.0f}s")
    await eng.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--max", dest="max_records", type=int, default=10000)
    parser.add_argument("--batch", type=int, default=100, help="commit every N records")
    args = parser.parse_args()
    asyncio.run(harvest(days=args.days, max_records=args.max_records, batch_commit=args.batch))


if __name__ == "__main__":
    main()
