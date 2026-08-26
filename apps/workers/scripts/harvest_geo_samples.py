"""GEO sample-level backfill — Series Matrix 에서 per-sample characteristics 수집.

전제:
- datasets 테이블에 GEO study-level 행이 이미 있다 (harvest_geo_large.py 가 먼저 실행).
- samples 테이블은 비어있거나 부분적. 본 스크립트가 채워넣는다.

처리:
- GEO datasets 를 (source_id, dataset_id) 페어로 스트림
- 각 GSE 에 대해 GeoMatrixHarvester.fetch_samples → samples UPSERT
- 100 GSE 단위 transaction commit

CLI:
    python -m scripts.harvest_geo_samples --limit 200 --concurrency 6
"""
from __future__ import annotations

import argparse
import asyncio
import time

from sqlalchemy import text

from src.db import get_engine
from src.harvesters.geo_matrix import GeoMatrixHarvester
from src.indexer.samples import index_samples


async def backfill(limit: int | None, concurrency: int, batch_commit: int) -> None:
    eng = get_engine()
    where_limit = f"LIMIT {int(limit)}" if limit else ""
    async with eng.connect() as conn:
        result = await conn.execute(
            text(
                f"""
                    SELECT id, source_id
                      FROM datasets
                     WHERE source_db = 'GEO'
                  ORDER BY submission_date DESC NULLS LAST
                       {where_limit}
                """
            )
        )
        targets = [(row[0], row[1]) for row in result.fetchall()]
    print(f"targets: {len(targets)} GSE")

    t0 = time.perf_counter()
    sem = asyncio.Semaphore(concurrency)
    total_samples = 0
    no_matrix = 0
    failed = 0

    async with GeoMatrixHarvester() as h:
        async def _one(dataset_id, gse) -> tuple[str, list[dict] | None, str | None]:
            async with sem:
                try:
                    samples = await h.fetch_samples(gse)
                    return gse, samples, None
                except Exception as e:
                    return gse, None, f"{type(e).__name__}: {str(e)[:80]}"

        i = 0
        while i < len(targets):
            chunk = targets[i : i + batch_commit]
            results = await asyncio.gather(*(_one(did, g) for did, g in chunk))
            async with eng.connect() as conn:
                async with conn.begin():
                    for (dataset_id, gse), (_gse, samples, err) in zip(chunk, results):
                        if err is not None:
                            failed += 1
                            if failed <= 5:
                                print(f"  fail {gse}: {err}")
                            continue
                        if not samples:
                            no_matrix += 1
                            continue
                        written = await index_samples(conn, dataset_id, samples)
                        total_samples += written
            i += len(chunk)
            elapsed = time.perf_counter() - t0
            print(
                f"  {i}/{len(targets)} | samples={total_samples} "
                f"no_matrix={no_matrix} failed={failed} | elapsed={elapsed:.0f}s"
            )
    await eng.dispose()
    print(
        f"\nbackfill done: samples={total_samples} no_matrix={no_matrix} "
        f"failed={failed} in {time.perf_counter() - t0:.0f}s"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="max GSE to process")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(
        backfill(limit=args.limit, concurrency=args.concurrency, batch_commit=args.batch)
    )


if __name__ == "__main__":
    main()
