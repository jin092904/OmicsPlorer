"""HCA 전체 projects ingest. 보통 수백 ~ 1000 건이라 single-pass.

사용:
    DATABASE_URL=... uv run python -u scripts/harvest_hca.py [--max N]

reindex 는 본 스크립트에서 안 함 — 호출자가 별도 step 으로 (다른 sources 와 합쳐서 1회).
"""
from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import text

from src.db import get_engine
from src.harvesters.hca import HcaHarvester
from src.indexer.hca import index_hca_record
from src.ontology.mapper import OntologyMapper


async def harvest(max_records: int | None = None, batch_commit: int = 50) -> None:
    eng = get_engine()
    t0 = time.perf_counter()

    async with HcaHarvester() as h, OntologyMapper() as mapper:
        # Azul 의 list_updated_since(매우 옛날) — 모든 project 가 yield
        ids: list[str] = []
        async for pid in h.list_updated_since(datetime(2000, 1, 1, tzinfo=timezone.utc)):
            ids.append(pid)
            if max_records and len(ids) >= max_records:
                break
        t_list = time.perf_counter() - t0
        print(f"hca list: {len(ids)} project ids in {t_list:.1f}s")

        inserted = 0
        skipped = 0
        i = 0
        while i < len(ids):
            chunk = ids[i : i + batch_commit]
            async with eng.connect() as conn:
                async with conn.begin():
                    for pid in chunk:
                        try:
                            raw = await h.fetch_raw(pid)
                            await index_hca_record(conn, raw, pid, mapper=mapper)
                            inserted += 1
                        except Exception as e:
                            skipped += 1
                            if skipped <= 5:
                                print(f"  skip {pid[:8]}: {type(e).__name__}: {str(e)[:80]}")
            i += len(chunk)
            elapsed = time.perf_counter() - t0
            print(f"  progress: {i}/{len(ids)} | inserted={inserted} skipped={skipped} | "
                  f"elapsed={elapsed:.0f}s")

    t_total = time.perf_counter() - t0
    print(f"\nhca ingest finished: inserted={inserted} skipped={skipped} in {t_total:.0f}s")

    async with eng.connect() as conn:
        result = await conn.execute(text("SELECT count(*) FROM datasets WHERE source_db='HCA'"))
        print(f"HCA total in DB: {result.scalar()}")
    await eng.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", dest="max_records", type=int, default=None)
    parser.add_argument("--batch", type=int, default=50)
    args = parser.parse_args()
    asyncio.run(harvest(max_records=args.max_records, batch_commit=args.batch))


if __name__ == "__main__":
    main()
