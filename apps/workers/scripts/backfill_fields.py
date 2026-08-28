"""필드 결정적 백필/정리 (2026-06-15 필드감사 후속). LLM 불필요 — 전부 SQL 결정적.

ops:
  garbage  — 교차온톨로지 쓰레기 제거(필드에 안 맞는 prefix CURIE drop, 원문/정상CURIE 유지)
             tissue: NCBITaxon|GO|CHEBI|PATO|COB / disease: HP|NCBITaxon|GO|MFOMD|AUG
             cell_type: UBERON|GO|NCBITaxon|CHEBI
  dates    — SRA submission_date 백필 (raw_metadata.raw.registration_date 'YYYY/MM/DD ...')
  organism — organism_taxid 백필: SRA=raw.sort_by_organism(int), GEO=samples Sample_taxid_ch1 union

변경분만 Qdrant payload + OpenSearch 동기화(배치). 변경 id 는 jsonl 로 기록.
실행:
  cd apps/workers
  DATABASE_URL=... QDRANT_URL=... OPENSEARCH_URL=... \\
  uv run python scripts/backfill_fields.py --dry-run
  uv run python scripts/backfill_fields.py --commit [--ops garbage,dates,organism]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.indexer.embeddings import (  # noqa: E402
    ensure_collection,
    get_qdrant_client,
)
from src.indexer.embeddings import (
    refresh_payloads as qdrant_refresh_payloads,
)
from src.indexer.lexical import (  # noqa: E402
    ensure_index,
    get_os_client,
)
from src.indexer.lexical import (
    upsert_many as os_upsert_many,
)

log = logging.getLogger("backfill-fields")
CHANGELOG = ROOT.parent.parent / "logs" / "backfill_fields_ids.jsonl"
SYNC_BATCH = 5000

GARBAGE = {
    "tissue_ids": "NCBITaxon|GO|CHEBI|PATO|COB",
    "disease_ids": "HP|NCBITaxon|GO|MFOMD|AUG",
    "cell_type_ids": "UBERON|GO|NCBITaxon|CHEBI",
}

# 각 op: (count_sql, update_sql). update 는 RETURNING id.
def _ops_sql() -> dict[str, tuple[str, str]]:
    ops: dict[str, tuple[str, str]] = {}
    for fld, prefixes in GARBAGE.items():
        rx = f"^({prefixes}):"
        cnt = f"SELECT count(*) FROM datasets WHERE EXISTS(SELECT 1 FROM unnest({fld}) x WHERE x ~ '{rx}')"
        upd = (f"UPDATE datasets SET {fld} = ARRAY(SELECT x FROM unnest({fld}) x WHERE x !~ '{rx}'), "
               "extraction_lineage_id = NULL, build_stage = NULL "
               f"WHERE EXISTS(SELECT 1 FROM unnest({fld}) x WHERE x ~ '{rx}') RETURNING id")
        ops[f"garbage:{fld}"] = (cnt, upd)
    ops["dates"] = (
        "SELECT count(*) FROM datasets WHERE source_db='SRA' AND submission_date IS NULL "
        "AND raw_metadata->'raw'->>'registration_date' ~ '^[0-9]{4}/[0-9]{2}/[0-9]{2}'",
        "UPDATE datasets SET submission_date = to_date(left(raw_metadata->'raw'->>'registration_date',10),'YYYY/MM/DD'), "
        "extraction_lineage_id = NULL, build_stage = NULL "
        "WHERE source_db='SRA' AND submission_date IS NULL "
        "AND raw_metadata->'raw'->>'registration_date' ~ '^[0-9]{4}/[0-9]{2}/[0-9]{2}' RETURNING id",
    )
    ops["organism:sra"] = (
        "SELECT count(*) FROM datasets WHERE source_db='SRA' AND cardinality(organism_taxid)=0 "
        "AND raw_metadata->'raw'->>'sort_by_organism' ~ '^[0-9]+$'",
        "UPDATE datasets SET organism_taxid = ARRAY[(raw_metadata->'raw'->>'sort_by_organism')::int], "
        "extraction_lineage_id = NULL, build_stage = NULL "
        "WHERE source_db='SRA' AND cardinality(organism_taxid)=0 "
        "AND raw_metadata->'raw'->>'sort_by_organism' ~ '^[0-9]+$' RETURNING id",
    )
    ops["organism:geo"] = (
        "SELECT count(*) FROM datasets d WHERE d.source_db='GEO' AND cardinality(d.organism_taxid)=0 "
        "AND EXISTS(SELECT 1 FROM samples s WHERE s.dataset_id=d.id AND s.raw_attributes->>'Sample_taxid_ch1' ~ '^[0-9]+$')",
        "UPDATE datasets d SET organism_taxid = sub.taxids, "
        "extraction_lineage_id = NULL, build_stage = NULL FROM ("
        "  SELECT s.dataset_id, array_agg(DISTINCT (s.raw_attributes->>'Sample_taxid_ch1')::int) taxids"
        "  FROM samples s WHERE s.raw_attributes->>'Sample_taxid_ch1' ~ '^[0-9]+$' GROUP BY s.dataset_id) sub "
        "WHERE d.id=sub.dataset_id AND d.source_db='GEO' AND cardinality(d.organism_taxid)=0 RETURNING d.id",
    )
    return ops


FETCH_SQL = """
SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
       disease_ids, tissue_ids, cell_type_ids, access_type, has_processed_data,
       submission_date, n_samples, n_subjects, platform, library_strategy, extraction_version
  FROM datasets WHERE id = ANY($1::uuid[])
"""


def _dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _selected(ops_arg: str) -> list[str]:
    all_ops = list(_ops_sql().keys())
    if not ops_arg:
        return all_ops
    want = set(ops_arg.split(","))
    return [k for k in all_ops if k.split(":")[0] in want or k in want]


async def run(*, commit: bool, ops_arg: str) -> dict[str, Any]:
    sql = _ops_sql()
    selected = _selected(ops_arg)
    pg = await asyncpg.connect(_dsn())
    changed: set[str] = set()
    counts: dict[str, int] = {}
    try:
        if not commit:
            for k in selected:
                counts[k] = await pg.fetchval(sql[k][0])
            log.info("DRY-RUN counts: %s", counts)
            return {"dry_run": True, **counts}

        for k in selected:
            rows = await pg.fetch(sql[k][1])
            ids = [str(r["id"]) for r in rows]
            counts[k] = len(ids)
            changed.update(ids)
            log.info("op %s: %d rows", k, len(ids))
        if not changed:
            return {"changed": 0, **counts}
        CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
        with CHANGELOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ops": selected, "counts": counts, "n_changed": len(changed)}, ensure_ascii=False) + "\n")
        changed_ids = list(changed)
    finally:
        # sync 단계에서 다시 fetch 하므로 여기선 닫지 않음
        pass

    # 변경분 배치 sync (재임베딩 없음)
    qdrant = get_qdrant_client()
    os_client = get_os_client()
    qn = on = 0
    try:
        await ensure_collection(qdrant)
        await ensure_index(os_client)
        for i in range(0, len(changed_ids), SYNC_BATCH):
            batch = changed_ids[i:i + SYNC_BATCH]
            rows = await pg.fetch(FETCH_SQL, batch)
            rd = [dict(r) for r in rows]
            qn += await qdrant_refresh_payloads(qdrant, rd)
            on += await os_upsert_many(os_client, rd)
            log.info("synced %d/%d", min(i + SYNC_BATCH, len(changed_ids)), len(changed_ids))
    finally:
        await qdrant.close()
        await os_client.close()
        await pg.close()
    log.info("DONE: changed=%d qdrant=%d os=%d counts=%s", len(changed_ids), qn, on, counts)
    return {"changed": len(changed_ids), "qdrant": qn, "opensearch": on, **counts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    ap.add_argument("--ops", default="", help="comma: garbage,dates,organism (default all)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(asyncio.run(run(commit=args.commit, ops_arg=args.ops)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
