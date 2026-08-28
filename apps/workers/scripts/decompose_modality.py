"""Compound modality 분해 — 멀티옴 라벨을 구성 모달리티로 펼침 (2026-06-14).

문제: scMultiome(1,035건) 중 scRNA-seq+scATAC-seq 로 함께 태깅된 건 74건뿐 → "scRNA and
      scATAC" 검색이 나머지 ~961건(실제 멀티옴)을 놓침. CITE-seq 도 RNA 성분이 있으나
      scRNA-seq 로 안 잡힘.
해법(결정적·규칙 기반, LLM/GPU 불필요, 추가만 = never-shrink):
  - scMultiome → scRNA-seq + scATAC-seq 보강
  - CITE-seq   → scRNA-seq 보강 (RNA 성분)
적용 후 변경분만 Qdrant payload + OpenSearch 에 sync (재임베딩 없음 — 텍스트 불변).

실행:
  cd apps/workers
  DATABASE_URL=... QDRANT_URL=... OPENSEARCH_URL=... \\
  uv run python scripts/decompose_modality.py --dry-run   # 건수만
  uv run python scripts/decompose_modality.py             # 적용 + sync
"""
from __future__ import annotations

import argparse
import asyncio
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

log = logging.getLogger("decompose-modality")

# (대상 라벨, 보강할 구성 모달리티들) — 추가만, 기존 제거 없음.
RULES = [
    ("scMultiome", ["scRNA-seq", "scATAC-seq"]),
    ("CITE-seq", ["scRNA-seq"]),
]

# 보강 대상: 라벨 보유 + 구성요소 중 누락분 존재. 추가는 누락분만(순서 보존).
COUNT_SQL = """
SELECT count(*) FROM datasets
 WHERE $1 = ANY(modality)
   AND EXISTS (SELECT 1 FROM unnest($2::text[]) m WHERE m <> ALL(modality))
"""
UPDATE_SQL = """
UPDATE datasets
   SET modality = modality || ARRAY(
         SELECT m FROM unnest($2::text[]) m WHERE m <> ALL(modality)),
       extraction_lineage_id = NULL,
       build_stage = NULL
 WHERE $1 = ANY(modality)
   AND EXISTS (SELECT 1 FROM unnest($2::text[]) m WHERE m <> ALL(modality))
RETURNING id
"""
FETCH_SQL = """
SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
       disease_ids, tissue_ids, cell_type_ids,
       access_type, has_processed_data, submission_date,
       n_samples, n_subjects, platform, library_strategy, extraction_version
  FROM datasets WHERE id = ANY($1::uuid[])
"""


def _dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def run(*, dry_run: bool) -> dict[str, Any]:
    pg = await asyncpg.connect(_dsn())
    changed_ids: set = set()
    try:
        if dry_run:
            res: dict[str, Any] = {"dry_run": True}
            for label, comps in RULES:
                n = await pg.fetchval(COUNT_SQL, label, comps)
                res[label] = n
                log.info("dry-run: %s → +%s 보강 대상 %d건", label, comps, n)
            return res

        for label, comps in RULES:
            rows = await pg.fetch(UPDATE_SQL, label, comps)
            changed_ids.update(r["id"] for r in rows)
            log.info("applied: %s → +%s, %d건 변경", label, comps, len(rows))

        if not changed_ids:
            log.info("변경 없음 — sync 생략")
            return {"changed": 0}

        rows = await pg.fetch(FETCH_SQL, list(changed_ids))
        row_dicts = [dict(r) for r in rows]
    finally:
        await pg.close()

    # 변경분만 sync (재임베딩 없음)
    qdrant = get_qdrant_client()
    os_client = get_os_client()
    try:
        await ensure_collection(qdrant)
        await ensure_index(os_client)
        qn = await qdrant_refresh_payloads(qdrant, row_dicts)
        on = await os_upsert_many(os_client, row_dicts)
    finally:
        await qdrant.close()
        await os_client.close()
    log.info("DONE: 변경 %d건, qdrant_payloads=%d opensearch=%d", len(changed_ids), qn, on)
    return {"changed": len(changed_ids), "qdrant_payloads": qn, "opensearch_upserts": on}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="건수만(쓰기 없음)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(asyncio.run(run(dry_run=args.dry_run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
