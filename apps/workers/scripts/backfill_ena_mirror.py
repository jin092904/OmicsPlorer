"""ENA mirror backfill — 모든 SRA dataset_sources row 에 ENA mirror row 보장.

설계:
  (dataset_id, source_id) 가 SRA 에 있는데 ENA 에 없는 row 를 찾아
  ENA row 하나를 idempotent 하게 INSERT.
  - raw_url: https://www.ebi.ac.uk/ena/browser/view/{source_id}  (PRJNA·SRP 둘 다 지원)
  - linked_via: 'ena-mirror'
  - is_primary: false
  PK (dataset_id, source_db, source_id) 위에 ON CONFLICT DO NOTHING — 동시 실행/재실행 안전.

호출:
  CLI:   uv run python apps/workers/scripts/backfill_ena_mirror.py [--dry-run]
  Celery beat: 매일 03:30 UTC (GEO 02:00 / HCA 02:30 / GDC 03:00 / **ENA 03:30** / reindex 04:00)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# scripts/ 에서 직접 실행할 때 src/ import 가능하도록
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from src.db import get_engine  # noqa: E402
from src.scheduling.watermark import set_watermark, source_lock  # noqa: E402

logger = logging.getLogger(__name__)

BACKFILL_SQL = text("""
INSERT INTO dataset_sources (dataset_id, source_db, source_id, raw_url, is_primary, linked_via)
SELECT
  sra.dataset_id,
  'ENA',
  sra.source_id,
  'https://www.ebi.ac.uk/ena/browser/view/' || sra.source_id,
  false,
  'ena-mirror'
FROM dataset_sources sra
WHERE sra.source_db = 'SRA'
  AND NOT EXISTS (
    SELECT 1 FROM dataset_sources ena
    WHERE ena.dataset_id = sra.dataset_id
      AND ena.source_db  = 'ENA'
      AND ena.source_id  = sra.source_id
  )
ON CONFLICT (dataset_id, source_db, source_id) DO NOTHING
""")

COUNT_SQL = text("""
SELECT
  (SELECT count(*) FROM dataset_sources WHERE source_db='SRA') AS sra,
  (SELECT count(*) FROM dataset_sources WHERE source_db='ENA') AS ena,
  (SELECT count(*) FROM dataset_sources sra
     WHERE sra.source_db='SRA'
       AND NOT EXISTS (
         SELECT 1 FROM dataset_sources ena
         WHERE ena.dataset_id=sra.dataset_id
           AND ena.source_db='ENA'
           AND ena.source_id=sra.source_id
       )) AS missing
""")


async def backfill_ena_mirror(*, dry_run: bool = False) -> dict[str, object]:
    """SRA row 마다 ENA mirror row 가 존재하도록 보장."""
    async with source_lock("ENA-backfill") as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "locked"}

        started = datetime.now(timezone.utc)
        eng = get_engine()
        try:
            # Phase 1: 사전 카운트 (autocommit-style)
            async with eng.connect() as conn:
                before = (await conn.execute(COUNT_SQL)).mappings().one()
                await conn.rollback()  # autobegin 해제
            logger.info(
                "before: sra=%d ena=%d missing=%d",
                before["sra"], before["ena"], before["missing"],
            )

            if dry_run:
                return {
                    "status": "dry-run",
                    "sra_rows": before["sra"],
                    "ena_rows": before["ena"],
                    "would_insert": before["missing"],
                }

            # Phase 2: 실제 백필 (자체 트랜잭션, AUTOCOMMIT 으로 commit 보장)
            async with eng.begin() as conn:
                result = await conn.execute(BACKFILL_SQL)
                inserted = result.rowcount or 0

            # Phase 3: 사후 카운트 (commit 이후 — 외부에서도 보이는 상태)
            async with eng.connect() as conn:
                after = (await conn.execute(COUNT_SQL)).mappings().one()
                await conn.rollback()
            logger.info(
                "after:  sra=%d ena=%d missing=%d inserted=%d",
                after["sra"], after["ena"], after["missing"], inserted,
            )

            await set_watermark("ENA-backfill", when=datetime.now(timezone.utc))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            return {
                "status": "ok",
                "sra_before": before["sra"],
                "ena_before": before["ena"],
                "missing_before": before["missing"],
                "inserted": inserted,
                "sra_after": after["sra"],
                "ena_after": after["ena"],
                "missing_after": after["missing"],
                "elapsed_s": round(elapsed, 2),
            }
        finally:
            await eng.dispose()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report missing count without inserting")
    args = parser.parse_args()

    result = asyncio.run(backfill_ena_mirror(dry_run=args.dry_run))
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("status") in {"ok", "dry-run", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
