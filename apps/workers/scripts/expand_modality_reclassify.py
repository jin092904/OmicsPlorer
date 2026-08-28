"""Rule-based modality reclassification — no LLM, no re-embedding.

목표:
  1. 28만 GEO 행의 modality 컬럼을 신규 vocab (29 종) 으로 재분류.
  2. Qdrant payload + OpenSearch doc refresh (벡터 미변경).

규칙 우선순위:
  A. **Hard override (gdstype 권위)** — GEO 가 큐레이션한 gdstype 은 LLM 보다 신뢰성 높음.
     - "Expression profiling by array"        → microarray (seq RNA 모달리티 제거)
     - "Non-coding RNA profiling by array"    → microarray
     - "Genome variation profiling by ... array" → SNP-array
     - "Genome binding/occupancy profiling by genome tiling array" → ChIP-chip
     - "Expression profiling by RT-PCR"       → RT-PCR
  B. **Soft addition (title regex)** — 기존 라벨에 ADD only.
     - CUT&RUN / CUT&Tag
     - snRNA-seq / single-nucleus
     - long-read (Nanopore/ONT/PacBio)
     - 16S
  C. 모달리티가 비면 'other' fallback.

소요: postgres UPDATE 28만 + Qdrant set_payload 28만 + OS bulk reindex 28만 ≈ 5–10분.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPORT_PATH = Path("/tmp/genofinder-modality-reclassify-report.json")

# Sequencing-based RNA expression modalities — gdstype 가 array 일 때 제거 대상.
SEQ_EXPRESSION_MODALITIES = {"bulk RNA-seq", "smallRNA-seq", "scRNA-seq", "snRNA-seq"}

# Title regex → 추가 모달리티 (additive).
TITLE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bCUT[\s&_-]?(?:and|&)?[\s_-]?(?:RUN|Tag)\b", re.I), "CUT&RUN"),
    (re.compile(r"\bsnRNA[-\s]?seq\b|\bsingle[-\s]?nucleus\b|\bsingle[-\s]?nuclei\b", re.I), "snRNA-seq"),
    (re.compile(r"\b(?:Nanopore|Oxford\s+Nanopore|ONT|PacBio|long[-\s]?reads?)\b", re.I), "long-read"),
    (re.compile(r"\b16[sS][-\s]?(?:rRNA|ribosomal|rDNA)|\b16[sS][-\s]?V[3-6]|\bV[34][-\s]?(?:region|hyperv)", re.I), "16S"),
]


def reclassify(
    current: list[str], gdstype: str | None, title: str | None
) -> tuple[list[str], list[str]]:
    """현 modality 를 받아 새 modality + 적용된 규칙 리스트 반환."""
    new = set(current or [])
    applied: list[str] = []
    gt = (gdstype or "").lower()
    title_s = title or ""

    # --- A. gdstype hard override -------------------------------------------
    if "expression profiling by array" in gt or "non-coding rna profiling by array" in gt:
        new = (new - SEQ_EXPRESSION_MODALITIES - {"other"}) | {"microarray"}
        applied.append("gdstype:expression_array→microarray")

    if "genome variation profiling by" in gt and "array" in gt:
        new = (new - {"WGS", "WES", "other"}) | {"SNP-array"}
        applied.append("gdstype:variation_array→SNP-array")

    if "genome binding/occupancy profiling by genome tiling array" in gt:
        new = (new - {"ChIP-seq", "other"}) | {"ChIP-chip"}
        applied.append("gdstype:binding_tiling→ChIP-chip")

    if "expression profiling by rt-pcr" in gt:
        new = (new - {"bulk RNA-seq", "other"}) | {"RT-PCR"}
        applied.append("gdstype:rt-pcr→RT-PCR")

    # --- B. title regex addition -------------------------------------------
    if title_s:
        for pattern, mod in TITLE_PATTERNS:
            if pattern.search(title_s):
                new.discard("other")
                new.add(mod)
                applied.append(f"title:{mod}")

    # --- C. fallback -------------------------------------------------------
    if not new:
        new = {"other"}

    return sorted(new), applied


def _pg_dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("ALEMBIC_DATABASE_URL or DATABASE_URL must be set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def update_postgres(conn: asyncpg.Connection) -> dict:
    """모든 GEO 행을 메모리로 가져와 재분류 후 UPDATE."""
    log.info("loading GEO datasets (id, modality, gdstype, title)…")
    t0 = time.perf_counter()
    rows = await conn.fetch(
        """
        SELECT id, modality,
               raw_metadata->'result'->(raw_metadata->'result'->'uids'->>0)->>'gdstype' AS gdstype,
               title
        FROM datasets WHERE source_db='GEO'
        """
    )
    log.info("  loaded %d rows in %.1fs", len(rows), time.perf_counter() - t0)

    changes: list[tuple[str, list[str]]] = []
    rule_counts: dict[str, int] = {}
    modality_delta: dict[str, int] = {}  # net change per modality
    sample_changes: list[dict] = []

    for r in rows:
        current = list(r["modality"] or [])
        new, applied = reclassify(current, r["gdstype"], r["title"])
        if sorted(current) != new:
            changes.append((str(r["id"]), new))
            for rule in applied:
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
            # delta per modality
            cset, nset = set(current), set(new)
            for m in nset - cset:
                modality_delta[m] = modality_delta.get(m, 0) + 1
            for m in cset - nset:
                modality_delta[m] = modality_delta.get(m, 0) - 1
            if len(sample_changes) < 30:
                sample_changes.append(
                    {"before": current, "after": new, "rules": applied}
                )

    log.info("  %d rows need modality update (%.1f%% of %d)",
             len(changes), 100.0 * len(changes) / len(rows), len(rows))

    if changes:
        log.info("UPDATE postgres in batches of 5000 …")
        t0 = time.perf_counter()
        batch = 5000
        for i in range(0, len(changes), batch):
            chunk = changes[i : i + batch]
            await conn.executemany(
                "UPDATE datasets SET modality=$2::text[], extraction_lineage_id=NULL, "
                "build_stage=NULL WHERE id=$1",
                chunk,
            )
            log.info("  updated %d / %d", min(i + batch, len(changes)), len(changes))
        log.info("  postgres UPDATE done in %.1fs", time.perf_counter() - t0)

    return {
        "total_geo": len(rows),
        "changed": len(changes),
        "rule_counts": dict(sorted(rule_counts.items(), key=lambda x: -x[1])),
        "modality_delta": dict(sorted(modality_delta.items(), key=lambda x: -x[1])),
        "samples": sample_changes,
    }


async def refresh_qdrant_and_opensearch() -> dict:
    """변경된 modality 가 검색 layer 에 반영되도록 payload + lexical doc 갱신."""
    log.info("refreshing Qdrant payloads + OpenSearch docs …")
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.indexer.lexical import get_os_client
    from src.indexer.lexical import upsert_many as os_upsert_many
    from src.indexer.pipeline import refresh_qdrant_payloads_only

    db_url = os.environ["DATABASE_URL"]
    eng = create_async_engine(db_url, pool_pre_ping=True)
    try:
        # Qdrant: set_payload 만 (벡터 보존)
        t0 = time.perf_counter()
        qd = await refresh_qdrant_payloads_only(eng)
        log.info("  qdrant refresh: %s in %.1fs", qd, time.perf_counter() - t0)

        # OpenSearch: bulk upsert (embedding 무관, document body 만 새로 작성)
        t0 = time.perf_counter()
        from sqlalchemy import text as sa_text

        async with eng.connect() as conn:
            result = await conn.execute(
                sa_text(
                    """
                    SELECT id, source_db, source_id, title, abstract,
                           modality, organism_taxid,
                           disease_ids, tissue_ids, cell_type_ids,
                           access_type, has_processed_data, submission_date,
                           n_samples, n_subjects, platform, library_strategy
                      FROM datasets
                    """
                )
            )
            rows = [dict(r._mapping) for r in result.fetchall()]
        os_client = get_os_client()
        try:
            os_count = await os_upsert_many(os_client, rows)
        finally:
            await os_client.close()
        log.info("  opensearch refresh: %d in %.1fs", os_count, time.perf_counter() - t0)
        return {"qdrant": qd, "opensearch_docs": os_count}
    finally:
        await eng.dispose()


async def main() -> None:
    log.info("Modality reclassification — starting")
    conn = await asyncpg.connect(_pg_dsn())
    try:
        pg = await update_postgres(conn)
    finally:
        await conn.close()

    idx = await refresh_qdrant_and_opensearch()

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "postgres": pg,
        "index_refresh": idx,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    log.info("=" * 60)
    log.info("✅ modality reclassification complete")
    log.info("  rows changed: %d / %d", pg["changed"], pg["total_geo"])
    log.info("  top rules:")
    for rule, n in list(pg["rule_counts"].items())[:8]:
        log.info("    %-40s  %d", rule, n)
    log.info("  modality delta (net):")
    for m, d in list(pg["modality_delta"].items())[:15]:
        sign = "+" if d > 0 else ""
        log.info("    %-20s  %s%d", m, sign, d)
    log.info("  qdrant: %s", idx["qdrant"])
    log.info("  opensearch docs: %d", idx["opensearch_docs"])
    log.info("  report → %s", REPORT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
