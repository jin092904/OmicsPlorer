"""모달리티 오태깅 정리 — GEO 서브시리즈 제목 마커를 권위로 모순 태그 교정 (2026-06-15).

문제: 추출 LLM 이 abstract 의 단어("single-cell" 등, 동반 데이터 언급)를 보고 bulk 서브시리즈에
      scRNA-seq 를 붙임(역도 발생). GEO 서브시리즈 제목의 '[bulk RNA-seq]' / '[scRNA-seq]'
      마커가 그 서브시리즈의 권위있는 어세이인데 무시됨. (예: GSE297038 '[bulk RNA-seq]' 인데
      modality=[bulk, scRNA-seq])

정리(고신뢰 + 보수적):
  A) 제목 '[bulk RNA-seq]' + modality 에 scRNA-seq/snRNA-seq + scMultiome 없음(decompose 정당분 제외)
     → scRNA-seq, snRNA-seq 제거 (bulk 등 나머지 유지)
  B) 제목 '[scRNA-seq]' + modality 에 bulk RNA-seq
     → bulk RNA-seq 제거 + scRNA-seq 보장(없으면 추가)

안 건드리는 것: 제목 마커가 없는 케이스(예: GSE291865)는 휴리스틱으로 못 가리므로 재추출(프롬프트
  개선) 영역으로 남김. 슈퍼시리즈/멀티옴 정당분도 제외.

변경분만 Qdrant payload + OpenSearch 동기화(재임베딩 없음). 모든 변경은 jsonl 로 감사/복구용 기록.

실행:
  cd apps/workers
  DATABASE_URL=... QDRANT_URL=... OPENSEARCH_URL=... \\
  uv run python scripts/fix_modality_mistag.py --dry-run   # 건수 + 샘플 before/after
  uv run python scripts/fix_modality_mistag.py --commit    # 적용 + sync
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

log = logging.getLogger("fix-modality-mistag")

CHANGELOG = ROOT.parent.parent / "logs" / "modality_mistag_changes.jsonl"

CANDIDATES_SQL = """
SELECT id, source_id, title, modality
  FROM datasets
 WHERE (
    (title ILIKE '%[bulk rna-seq]%'
       AND ('scRNA-seq' = ANY(modality) OR 'snRNA-seq' = ANY(modality))
       AND NOT 'scMultiome' = ANY(modality))
    OR
    (title ILIKE '%[scrna-seq]%' AND 'bulk RNA-seq' = ANY(modality))
 )
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


def _new_modality(title: str, mod: list[str]) -> list[str]:
    """제목 마커를 권위로 모순 태그만 교정. 입력 순서 보존."""
    title_l = (title or "").lower()
    mod_l = {m.lower() for m in mod}
    new = list(mod)
    # A) bulk 서브시리즈 → 단일세포 RNA 태그 제거 (멀티옴 정당분은 위 SQL 에서 이미 제외)
    if "[bulk rna-seq]" in title_l and "scmultiome" not in mod_l:
        new = [m for m in new if m not in ("scRNA-seq", "snRNA-seq")]
    # B) scRNA 서브시리즈 → bulk 제거 + scRNA-seq 보장
    if "[scrna-seq]" in title_l:
        new = [m for m in new if m != "bulk RNA-seq"]
        if "scRNA-seq" not in new:
            new = new + ["scRNA-seq"]
    return new


async def run(*, commit: bool) -> dict[str, Any]:
    pg = await asyncpg.connect(_dsn())
    changes: list[dict[str, Any]] = []
    try:
        rows = await pg.fetch(CANDIDATES_SQL)
        for r in rows:
            old = list(r["modality"] or [])
            new = _new_modality(r["title"] or "", old)
            if new != old:
                changes.append({
                    "id": str(r["id"]), "source_id": r["source_id"],
                    "title": (r["title"] or "")[:90], "old": old, "new": new,
                })

        if not commit:
            log.info("DRY-RUN: 정리 대상 %d건", len(changes))
            for ch in changes[:12]:
                log.info("  %s  %s -> %s  | %s", ch["source_id"], ch["old"], ch["new"], ch["title"])
            return {"dry_run": True, "would_change": len(changes)}

        if not changes:
            log.info("변경 없음")
            return {"changed": 0}

        # 감사/복구 로그 (old 보존)
        CHANGELOG.parent.mkdir(parents=True, exist_ok=True)
        with CHANGELOG.open("a", encoding="utf-8") as f:
            for ch in changes:
                f.write(json.dumps(ch, ensure_ascii=False) + "\n")

        # per-id UPDATE (정확 제어)
        async with pg.transaction():
            for ch in changes:
                await pg.execute(
                    "UPDATE datasets SET modality = $2, extraction_lineage_id = NULL, "
                    "build_stage = NULL WHERE id = $1::uuid",
                    ch["id"], ch["new"],
                )
        changed_ids = [ch["id"] for ch in changes]
        log.info("applied: %d건 modality 교정 (changelog: %s)", len(changed_ids), CHANGELOG)

        rows2 = await pg.fetch(FETCH_SQL, changed_ids)
        row_dicts = [dict(r) for r in rows2]
    finally:
        await pg.close()

    # 변경분만 sync (재임베딩 없음 — 텍스트 불변)
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
    return {"changed": len(changes), "qdrant_payloads": qn, "opensearch_upserts": on}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="건수 + 샘플만(기본)")
    g.add_argument("--commit", action="store_true", help="적용 + sync")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(asyncio.run(run(commit=args.commit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
