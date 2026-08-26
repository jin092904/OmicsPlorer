"""PubMed augmentation — 짧은 abstract 데이터셋의 abstract 필드를 PubMed 의 풍부한 abstract 로 보강.

타겟 (예측 47,560건):
  - source_db = 'GEO'
  - LENGTH(abstract) < 200
  - raw_metadata.pubmedids 비어있지 않음

처리:
  1. Postgres 에서 target rows + 첫 PMID 추출
  2. NCBI EUtils efetch (db=pubmed) 배치 200개씩 → XML parse → AbstractText 추출
  3. UPDATE datasets SET abstract = original || '\n\n[PubMed PMID:...] ' || pubmed_abstract
     (원본 보존 + PubMed augmentation 표시)
  4. 보강된 항목들의 Qdrant 임베딩 재계산 (qwen3-embedding:8b)
  5. OpenSearch 문서 재인덱싱

총 소요: 약 1시간 (NCBI 10rps × 47k/200 ≈ 4분 efetch + 임베딩 ~25분 + OS upsert ~5분).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPORT_PATH = Path("/tmp/genofinder-pubmed-augment-report.json")
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
BATCH_SIZE = 200  # PMID/batch — efetch supports up to ~200 ids
ABSTRACT_LEN_THRESHOLD = 200


def _pg_dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ─────────────────────────── PubMed fetch ──────────────────────────────
def _extract_abstract_xml(article_xml: ET.Element) -> str | None:
    """Extract abstract text from PubMed XML <PubmedArticle> element.

    Handles structured abstracts with <AbstractText Label="BACKGROUND">…</AbstractText>.
    """
    abstract_el = article_xml.find(".//Abstract")
    if abstract_el is None:
        return None
    parts: list[str] = []
    for at in abstract_el.findall("AbstractText"):
        label = at.get("Label")
        text = "".join(at.itertext()).strip()
        if not text:
            continue
        if label and label.lower() not in ("unlabelled", "none"):
            parts.append(f"{label}: {text}")
        else:
            parts.append(text)
    if not parts:
        return None
    return " ".join(parts).strip()


async def fetch_pubmed_batch(
    client: httpx.AsyncClient, pmids: list[str], api_key: str | None
) -> dict[str, str]:
    """PMID list → {pmid: abstract_text}."""
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key
    resp = await client.get(f"{EUTILS_BASE}/efetch.fcgi", params=params, timeout=60.0)
    resp.raise_for_status()
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as e:
        log.warning("XML parse failed: %s", e)
        return {}
    result: dict[str, str] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None else None
        if not pmid:
            continue
        abstract = _extract_abstract_xml(article)
        if abstract and len(abstract) > 50:
            result[pmid] = abstract
    return result


# ──────────────────────────── main flow ────────────────────────────────
async def step1_load_targets(conn: asyncpg.Connection) -> list[dict]:
    log.info("step 1 — load target GEO datasets")
    rows = await conn.fetch(
        f"""
        SELECT
          id, source_id,
          abstract,
          (raw_metadata->'result'->(raw_metadata->'result'->'uids'->>0)->'pubmedids'->>0) AS pmid
        FROM datasets
        WHERE source_db = 'GEO'
          AND LENGTH(COALESCE(abstract, '')) < {ABSTRACT_LEN_THRESHOLD}
          AND jsonb_array_length(
            COALESCE(raw_metadata->'result'->(raw_metadata->'result'->'uids'->>0)->'pubmedids', '[]'::jsonb)
          ) > 0
        """
    )
    log.info("  %d candidates loaded", len(rows))
    return [dict(r) for r in rows]


async def step2_fetch_and_update(
    conn: asyncpg.Connection, targets: list[dict]
) -> dict:
    log.info("step 2 — PubMed efetch + UPDATE (batch=%d)", BATCH_SIZE)
    api_key = os.environ.get("NCBI_EUTILS_API_KEY")
    if api_key:
        log.info("  using NCBI API key (10 rps)")
    else:
        log.warning("  no NCBI API key — 3 rps")

    # Build pmid → [target rows] map (multiple GSEs can share a PMID)
    pmid_to_targets: dict[str, list[dict]] = {}
    for t in targets:
        pmid = t["pmid"]
        if pmid:
            pmid_to_targets.setdefault(pmid, []).append(t)
    unique_pmids = list(pmid_to_targets.keys())
    log.info("  %d unique PMIDs across %d targets", len(unique_pmids), len(targets))

    min_interval = 1.0 / (10.0 if api_key else 3.0)
    last_call = 0.0
    augmented_count = 0
    fetched_count = 0
    failed_batches = 0

    async with httpx.AsyncClient(
        headers={"User-Agent": "OmicsPlorer/1.0 (research)"}
    ) as client:
        for i in range(0, len(unique_pmids), BATCH_SIZE):
            batch = unique_pmids[i : i + BATCH_SIZE]
            elapsed = time.perf_counter() - last_call
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            try:
                result = await fetch_pubmed_batch(client, batch, api_key)
            except Exception as e:
                log.warning("  batch %d-%d failed: %s", i, i + len(batch), e)
                failed_batches += 1
                last_call = time.perf_counter()
                continue
            last_call = time.perf_counter()
            fetched_count += len(result)

            # UPDATE each target whose PMID is in result
            updates: list[tuple] = []
            for pmid, pubmed_text in result.items():
                for t in pmid_to_targets.get(pmid, []):
                    orig = (t["abstract"] or "").strip()
                    if orig and orig.lower() not in ("data", "test", "abstract", "1"):
                        new_abs = f"{orig}\n\n[PubMed PMID:{pmid}] {pubmed_text}"
                    else:
                        new_abs = f"[PubMed PMID:{pmid}] {pubmed_text}"
                    updates.append((str(t["id"]), new_abs))

            if updates:
                await conn.executemany(
                    "UPDATE datasets SET abstract = $2 WHERE id = $1",
                    updates,
                )
                augmented_count += len(updates)

            if (i // BATCH_SIZE) % 10 == 0:
                log.info(
                    "  batch %d/%d, fetched %d PMIDs, augmented %d rows so far",
                    i // BATCH_SIZE + 1,
                    (len(unique_pmids) + BATCH_SIZE - 1) // BATCH_SIZE,
                    fetched_count,
                    augmented_count,
                )

    log.info("  total: fetched %d PMIDs, augmented %d rows, %d failed batches",
             fetched_count, augmented_count, failed_batches)
    return {
        "unique_pmids": len(unique_pmids),
        "fetched_abstracts": fetched_count,
        "augmented_rows": augmented_count,
        "failed_batches": failed_batches,
    }


async def step3_reindex_augmented_ids(augmented_ids: list[str]) -> dict:
    """보강된 행들의 Qdrant 임베딩 재계산 + OS 문서 재인덱싱."""
    if not augmented_ids:
        log.info("step 3 — nothing to reindex")
        return {"qdrant_upserts": 0, "opensearch_upserts": 0}

    log.info("step 3 — re-embed %d rows + OS refresh", len(augmented_ids))
    from src.extractors.llm_client import OllamaClient
    from src.indexer.embeddings import get_qdrant_client
    from src.indexer.embeddings import upsert_many as qdrant_upsert
    from src.indexer.lexical import get_os_client
    from src.indexer.lexical import upsert_many as os_upsert

    conn = await asyncpg.connect(_pg_dsn())
    try:
        rows_raw = await conn.fetch(
            """
            SELECT id, source_db, source_id, title, abstract,
                   modality, organism_taxid,
                   disease_ids, tissue_ids, cell_type_ids,
                   access_type, has_processed_data, submission_date,
                   n_samples, n_subjects, platform, library_strategy
            FROM datasets
            WHERE id::text = ANY($1)
            """,
            augmented_ids,
        )
    finally:
        await conn.close()
    rows = [dict(r) for r in rows_raw]
    log.info("  loaded %d rows for reindex", len(rows))

    qdrant = get_qdrant_client()
    ollama = OllamaClient()
    try:
        qd_n = await qdrant_upsert(qdrant, ollama, rows)
    finally:
        await qdrant.close()
    log.info("  Qdrant re-embedded: %d", qd_n)

    os_client = get_os_client()
    try:
        os_n = await os_upsert(os_client, rows)
    finally:
        await os_client.close()
    log.info("  OpenSearch upserted: %d", os_n)

    return {"qdrant_upserts": qd_n, "opensearch_upserts": os_n}


async def main() -> None:
    t0 = time.perf_counter()
    log.info("PubMed abstract augment — starting")
    conn = await asyncpg.connect(_pg_dsn())
    try:
        targets = await step1_load_targets(conn)
        # Snapshot IDs before update (so we know which to reindex)
        target_ids = [str(t["id"]) for t in targets]
        stats = await step2_fetch_and_update(conn, targets)
    finally:
        await conn.close()

    # Re-collect actually augmented IDs (those that got a PubMed abstract)
    conn = await asyncpg.connect(_pg_dsn())
    try:
        augmented_ids = await conn.fetch(
            "SELECT id::text FROM datasets WHERE id::text = ANY($1) AND abstract LIKE '%[PubMed PMID:%'",
            target_ids,
        )
    finally:
        await conn.close()
    augmented_id_list = [r["id"] for r in augmented_ids]
    log.info("  %d rows actually augmented (have PubMed marker)", len(augmented_id_list))

    reindex_stats = await step3_reindex_augmented_ids(augmented_id_list)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "targets_total": len(targets),
        "fetch": stats,
        "reindex": reindex_stats,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    log.info("=" * 60)
    log.info("✅ PubMed augment complete in %.1fs", report["elapsed_s"])
    log.info("  candidates           : %d", report["targets_total"])
    log.info("  PubMed fetched       : %d", stats["fetched_abstracts"])
    log.info("  rows augmented       : %d", stats["augmented_rows"])
    log.info("  Qdrant re-embedded   : %d", reindex_stats["qdrant_upserts"])
    log.info("  OpenSearch upserted  : %d", reindex_stats["opensearch_upserts"])
    log.info("  report → %s", REPORT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
