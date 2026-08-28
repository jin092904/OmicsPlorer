"""모달리티 보정 — per-sample 증거(GEO Sample_library_source/data_processing)로 bulk↔단일세포
결정 (2026-06-15). #3 골드스탠다드 + #2 의 제목마커 없는 케이스를 동시 해결.

근거: GEO 샘플 메타데이터에 권위있는 assay 신호가 이미 있음(재수확 불필요):
  - Sample_library_source = 'transcriptomic single cell' / 'transcriptomic single nucleus' → 단일세포
  - Sample_library_source = 'transcriptomic' (single 없음) + library_strategy='RNA-Seq' → bulk
  - Sample_data_processing 에 Cell Ranger / STARsolo / single-nuclei / 10x / Seurat / scanpy → 단일세포
이건 abstract 언급이 아니라 '이 데이터셋 자신의 샘플'이라 결정적.

대상: bulk RNA-seq + (scRNA-seq|snRNA-seq) 동시 태깅(=혼동 의심) 중 샘플 보유.
보정(보수적, 모순만):
  - 샘플 증거 bulk-only(has_bulk & !has_sc) → scRNA-seq, snRNA-seq 제거(bulk 유지)
  - 샘플 증거 sc-only (has_sc & !has_bulk) → bulk RNA-seq 제거(sc 유지)
  - 혼합(has_sc & has_bulk) 또는 판정불가 → 변경 없음(정당하거나 근거 부족)

변경분만 Qdrant+OS 동기화. 모든 변경 jsonl 감사로그(복구용).

실행:
  cd apps/workers
  DATABASE_URL=... QDRANT_URL=... OPENSEARCH_URL=... \\
  uv run python scripts/fix_modality_from_samples.py --dry-run   # 분류·건수·샘플
  uv run python scripts/fix_modality_from_samples.py --commit    # 적용 + sync
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

log = logging.getLogger("fix-modality-from-samples")
CHANGELOG = ROOT.parent.parent / "logs" / "modality_from_samples_changes.jsonl"

# 후보 + per-sample 증거 집계. SC 신호 / BULK 신호를 bool_or 로.
EVIDENCE_SQL = """
WITH cand AS (
  SELECT id, source_id, title, modality
    FROM datasets
   WHERE 'bulk RNA-seq' = ANY(modality)
     AND ('scRNA-seq' = ANY(modality) OR 'snRNA-seq' = ANY(modality))
)
SELECT c.id, c.source_id, c.modality,
  bool_or(
       (s.raw_attributes->>'Sample_library_source') ILIKE '%single cell%'
    OR (s.raw_attributes->>'Sample_library_source') ILIKE '%single nucleus%'
    OR (s.raw_attributes->>'Sample_data_processing') ~* '(cell ?ranger|starsolo|single[- ]nuc|single[- ]cell|seurat|scanpy|10x genomics|chromium)'
  ) AS has_sc,
  bool_or(
       (s.raw_attributes->>'Sample_library_source') IS NOT NULL
   AND (s.raw_attributes->>'Sample_library_source') NOT ILIKE '%single%'
   AND (s.raw_attributes->>'Sample_library_strategy') ILIKE 'RNA-Seq'
  ) AS has_bulk,
  count(s.*) AS n_samp
FROM cand c
LEFT JOIN samples s ON s.dataset_id = c.id
GROUP BY c.id, c.source_id, c.modality
"""

FETCH_SQL = """
SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
       disease_ids, tissue_ids, cell_type_ids,
       access_type, has_processed_data, submission_date,
       n_samples, n_subjects, platform, library_strategy, extraction_version
  FROM datasets WHERE id = ANY($1::uuid[])
"""

SC_TAGS = ("scRNA-seq", "snRNA-seq")


def _dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _corrected(mod: list[str], has_sc: bool, has_bulk: bool) -> list[str] | None:
    """샘플 증거가 모달리티와 모순될 때만 보정. 아니면 None(변경 없음)."""
    if has_bulk and not has_sc:
        new = [m for m in mod if m not in SC_TAGS]
        return new if new != mod else None
    if has_sc and not has_bulk:
        new = [m for m in mod if m != "bulk RNA-seq"]
        return new if new != mod else None
    return None


async def run(*, commit: bool) -> dict[str, Any]:
    pg = await asyncpg.connect(_dsn())
    changes: list[dict[str, Any]] = []
    stats = {"candidates": 0, "no_samples": 0, "mixed_legit": 0, "to_fix": 0}
    try:
        rows = await pg.fetch(EVIDENCE_SQL)
        stats["candidates"] = len(rows)
        for r in rows:
            if not r["n_samp"]:
                stats["no_samples"] += 1
                continue
            if r["has_sc"] and r["has_bulk"]:
                stats["mixed_legit"] += 1
                continue
            old = list(r["modality"] or [])
            new = _corrected(old, r["has_sc"], r["has_bulk"])
            if new is not None:
                changes.append({
                    "id": str(r["id"]), "source_id": r["source_id"],
                    "old": old, "new": new,
                    "has_sc": r["has_sc"], "has_bulk": r["has_bulk"], "n_samp": r["n_samp"],
                })
        stats["to_fix"] = len(changes)

        if not commit:
            log.info("DRY-RUN stats: %s", stats)
            for ch in changes[:12]:
                log.info("  %s  %s -> %s  (sc=%s bulk=%s n=%s)",
                         ch["source_id"], ch["old"], ch["new"], ch["has_sc"], ch["has_bulk"], ch["n_samp"])
            return {"dry_run": True, **stats}

        if not changes:
            log.info("변경 없음")
            return {"changed": 0, **stats}

        CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
        with CHANGELOG.open("a", encoding="utf-8") as f:
            for ch in changes:
                f.write(json.dumps(ch, ensure_ascii=False) + "\n")

        async with pg.transaction():
            for ch in changes:
                await pg.execute(
                    "UPDATE datasets SET modality = $2, extraction_lineage_id = NULL, "
                    "build_stage = NULL WHERE id = $1::uuid",
                    ch["id"], ch["new"],
                )
        changed_ids = [ch["id"] for ch in changes]
        log.info("applied: %d건 (changelog: %s)", len(changed_ids), CHANGELOG)

        rows2 = await pg.fetch(FETCH_SQL, changed_ids)
        row_dicts = [dict(r) for r in rows2]
    finally:
        await pg.close()

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
    log.info("DONE: 변경 %d건, qdrant=%d opensearch=%d", len(changes), qn, on)
    return {"changed": len(changes), "qdrant_payloads": qn, "opensearch_upserts": on, **stats}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="분류·건수·샘플만")
    g.add_argument("--commit", action="store_true", help="적용 + sync")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(asyncio.run(run(commit=args.commit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
