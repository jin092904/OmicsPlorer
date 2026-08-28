"""Create/update the OpenSearch lexical index from PostgreSQL without an embedding model."""
from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from src.db import get_engine
from src.indexer.lexical import ensure_index, get_os_client, upsert_many


async def main() -> int:
    engine = get_engine()
    client = get_os_client()
    try:
        await ensure_index(client)
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
                       disease_ids, tissue_ids, cell_type_ids, access_type,
                       has_processed_data, submission_date, n_samples, n_subjects,
                       platform, library_strategy, extraction_version,
                       extraction_lineage_id, build_stage
                  FROM datasets ORDER BY submission_date DESC NULLS LAST
            """))
            rows = [dict(row._mapping) for row in result.fetchall()]
        indexed = await upsert_many(client, rows)
        await client.indices.refresh(index="datasets_v2")
        print(json.dumps({"datasets_in_db": len(rows), "opensearch_upserts": indexed}))
        return 0
    finally:
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
