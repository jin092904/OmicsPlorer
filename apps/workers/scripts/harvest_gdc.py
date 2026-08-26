"""GDC 전체 projects ingest. 91 records."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import text

from src.db import get_engine
from src.harvesters.gdc import GdcHarvester
from src.indexer.gdc import index_gdc_record
from src.ontology.mapper import OntologyMapper


async def harvest() -> None:
    eng = get_engine()
    t0 = time.perf_counter()
    async with GdcHarvester() as h, OntologyMapper() as mapper:
        ids: list[str] = []
        async for pid in h.list_updated_since(datetime(2000, 1, 1, tzinfo=timezone.utc)):
            ids.append(pid)
        print(f"gdc list: {len(ids)} project ids in {time.perf_counter()-t0:.1f}s")

        inserted = 0
        skipped = 0
        async with eng.connect() as conn:
            async with conn.begin():
                for i, pid in enumerate(ids, 1):
                    try:
                        raw = await h.fetch_raw(pid)
                        await index_gdc_record(conn, raw, pid, mapper=mapper)
                        inserted += 1
                    except Exception as e:
                        skipped += 1
                        print(f"  skip {pid}: {type(e).__name__}: {str(e)[:80]}")
                    if i % 10 == 0:
                        print(f"  {i}/{len(ids)} done, inserted={inserted}")

    print(f"\ngdc ingest finished: inserted={inserted} skipped={skipped} in {time.perf_counter()-t0:.0f}s")
    async with eng.connect() as conn:
        result = await conn.execute(text("SELECT count(*) FROM datasets WHERE source_db='GDC'"))
        print(f"GDC total in DB: {result.scalar()}")
    await eng.dispose()


if __name__ == "__main__":
    asyncio.run(harvest())
