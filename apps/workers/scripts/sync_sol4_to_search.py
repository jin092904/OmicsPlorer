"""Sol4 재태깅 결과(Postgres 태그 변경)를 Qdrant payload + OpenSearch 에 동기화.

왜 재임베딩이 필요 없나:
  Sol4 는 datasets 의 tissue_ids/cell_type_ids/disease_ids/cohort_design 만 바꿨고 텍스트
  (title/abstract)는 안 건드렸다. 임베딩 입력(_compose_text)은 title+abstract+platform 뿐이라
  태그를 포함하지 않으므로 dense 벡터는 그대로 유효하다. 따라서:
    - Qdrant : payload(태그 메타데이터)만 overwrite — 벡터 미변경, GPU 0.
    - OpenSearch : BM25 재색인(임베딩 없음) — GPU 0.
  전체 재임베딩은 불필요하다. 실제 처리 시간은 코퍼스 크기와 하드웨어에 따라 달라진다.

대상: extraction_version = --version 인 datasets (Sol4 1회성 런 + 향후 self-healing auto 도
      동일 EXTRACTION_VERSION 을 찍으므로 그대로 재사용 가능).

전제: Sol4 가 처리한 dataset 은 이미 코퍼스에 색인되어 있음(점이 존재) → refresh_payloads 가
      기존 점의 payload 만 갱신. 미색인 dataset 은 refresh 대상이 없어 조용히 건너뜀(별도 full
      embed 필요 — Sol4 대상엔 해당 없음).

실행 (Sol4 1회성 런 완전 종료 후):
  cd apps/workers
  DATABASE_URL=... QDRANT_URL=... OPENSEARCH_URL=... \\
  uv run python scripts/sync_sol4_to_search.py            # 실제 동기화
  uv run python scripts/sync_sol4_to_search.py --dry-run  # 건수만(읽기전용, 안전)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

# scripts/ 에서 직접 실행할 때 src/ import 가능하도록
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import get_engine  # noqa: E402
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

log = logging.getLogger("sol4-sync")

EXTRACTION_VERSION = "sol4-gemma4-2026-06-07"

# reindex_all_search_layers 와 동일한 컬럼 집합(_payload / os _to_doc 가 기대하는 superset).
SELECT_SQL = """
SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
       disease_ids, tissue_ids, cell_type_ids,
       access_type, has_processed_data, submission_date,
       n_samples, n_subjects, platform, library_strategy, extraction_version
  FROM datasets
 WHERE extraction_version = :ver
 ORDER BY submission_date DESC NULLS LAST
"""

COUNT_SQL = "SELECT count(*) AS n FROM datasets WHERE extraction_version = :ver"


async def sync(*, version: str, dry_run: bool) -> dict[str, Any]:
    eng = get_engine()
    try:
        async with eng.connect() as conn:
            n = (await conn.execute(text(COUNT_SQL), {"ver": version})).scalar_one()
            log.info("sol4-sync: %d datasets at extraction_version=%s", n, version)
            if dry_run:
                return {"datasets": int(n), "dry_run": True}
            res = await conn.execute(text(SELECT_SQL), {"ver": version})
            rows = [dict(r._mapping) for r in res.fetchall()]

        qdrant = get_qdrant_client()
        os_client = get_os_client()
        try:
            await ensure_collection(qdrant)
            await ensure_index(os_client)
            qn = await qdrant_refresh_payloads(qdrant, rows)   # 벡터 미변경, payload만
            on = await os_upsert_many(os_client, rows)         # BM25 재색인(임베딩 없음)
        finally:
            await qdrant.close()
            await os_client.close()
        log.info("sol4-sync DONE: qdrant_payloads=%d opensearch_upserts=%d", qn, on)
        return {"datasets": len(rows), "qdrant_payloads_updated": qn, "opensearch_upserts": on}
    finally:
        await eng.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=EXTRACTION_VERSION,
                        help=f"동기화할 extraction_version (default {EXTRACTION_VERSION})")
    parser.add_argument("--dry-run", action="store_true",
                        help="대상 건수만 출력(읽기전용, Qdrant/OS write 없음)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = asyncio.run(sync(version=args.version, dry_run=args.dry_run))
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
