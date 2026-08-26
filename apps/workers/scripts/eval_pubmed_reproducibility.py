"""PubMed Reproducibility Benchmark — 외부 객관 평가.

Ground truth = 한 PubMed paper 가 여러 GEO accession 을 인용한 사실 관계.
  - 32,357 PMIDs 가 GEO 2개 이상 인용 (Phase 1+PubMed augment 데이터 기반)
  - paper abstract → query, 인용된 GEO 들 → expected results
  - 100% 객관 (사람 판단 X, 인용 관계 = ground truth)

평가 메트릭:
  - recall@10/20/50 — top-K 중 expected GEO 가 몇 % 등장
  - hit@10 (binary) — top-10 에 적어도 1건
  - MRR — 첫 번째 expected 의 reciprocal rank
  - 모드 비교 (bm25_only / dense_only / rrf / rrf_rerank)

샘플링:
  - 다중 GEO 인용 PMID 중 GEO 2-10 인용 범위 (interpretable)
  - 200건 sample (시연용; 논문에서 늘릴 수 있음)

소요: 약 30-60분 (PubMed efetch 200 + search 200 × 4 modes = 800 search 호출)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import statistics
import time
from pathlib import Path

import asyncpg
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPORT_PATH = Path("/tmp/genofinder-eval-pubmed-repro.json")
EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
SEARCH_API = "http://localhost:8000/api/v1/search"

N_SAMPLE = 200      # 평가용 PMID 수
GEO_RANGE = (2, 10) # 인용 GEO 수 범위
PAGE_SIZE = 50      # top-K to evaluate
MODES = ["bm25_only", "dense_only", "rrf", "rrf_rerank"]
RANDOM_SEED = 42


def _pg_dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def sample_test_queries(conn: asyncpg.Connection) -> list[dict]:
    """다중 GEO 인용 PMID 샘플 + 각 PMID 의 expected GEOs."""
    log.info("sampling %d PMIDs with %d-%d cited GEOs…", N_SAMPLE, *GEO_RANGE)
    rows = await conn.fetch(
        f"""
        WITH pmid_geo AS (
          SELECT
            pmid::text AS pmid,
            d.source_id AS geo_acc
          FROM datasets d,
            LATERAL jsonb_array_elements_text(
              COALESCE(d.raw_metadata->'result'->(d.raw_metadata->'result'->'uids'->>0)->'pubmedids', '[]'::jsonb)
            ) AS pmid
          WHERE d.source_db='GEO'
        ),
        pmid_groups AS (
          SELECT pmid, array_agg(DISTINCT geo_acc ORDER BY geo_acc) AS geos
          FROM pmid_geo GROUP BY pmid
          HAVING COUNT(DISTINCT geo_acc) BETWEEN {GEO_RANGE[0]} AND {GEO_RANGE[1]}
        )
        SELECT pmid, geos FROM pmid_groups
        ORDER BY random()
        LIMIT {N_SAMPLE * 2}  -- 2x oversample (some may fail PubMed fetch)
        """
    )
    log.info("  %d candidates loaded", len(rows))
    return [{"pmid": r["pmid"], "expected_geos": list(r["geos"])} for r in rows]


async def fetch_pubmed_abstracts(
    candidates: list[dict], api_key: str | None
) -> dict[str, dict]:
    """PMID → {title, abstract}. PubMed efetch batch."""
    log.info("fetching PubMed abstracts via efetch…")
    from xml.etree import ElementTree as ET

    pmids = [c["pmid"] for c in candidates]
    out: dict[str, dict] = {}
    batch = 100
    min_interval = 0.1 if api_key else 0.34  # 10rps with key, 3rps without
    last_call = 0.0

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i in range(0, len(pmids), batch):
            chunk = pmids[i : i + batch]
            elapsed = time.perf_counter() - last_call
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
            params = {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}
            if api_key:
                params["api_key"] = api_key
            try:
                resp = await client.get(f"{EUTILS_BASE}/efetch.fcgi", params=params)
                last_call = time.perf_counter()
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
            except Exception as e:
                log.warning("  batch %d efetch failed: %s", i, e)
                continue
            for article in root.findall(".//PubmedArticle"):
                pmid_el = article.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None else None
                if not pmid:
                    continue
                title_el = article.find(".//ArticleTitle")
                title = "".join(title_el.itertext()).strip() if title_el is not None else ""
                abs_el = article.find(".//Abstract")
                if abs_el is None:
                    continue
                parts = []
                for at in abs_el.findall("AbstractText"):
                    text = "".join(at.itertext()).strip()
                    if text:
                        parts.append(text)
                abstract = " ".join(parts).strip()
                if title and abstract and len(abstract) > 100:
                    out[pmid] = {"title": title, "abstract": abstract}
            if (i // batch) % 5 == 0:
                log.info("  efetch %d/%d, abstracts %d", i + batch, len(pmids), len(out))
    log.info("  fetched %d abstracts", len(out))
    return out


async def run_search(
    client: httpx.AsyncClient, query_text: str, mode: str
) -> list[str]:
    """검색 호출 → top-K source_ids 반환 (GEO accessions only)."""
    headers = {"Content-Type": "application/json"}
    if mode != "rrf_rerank":
        headers["X-Eval-Mode"] = "1"
    body = {
        "query_text": query_text,
        "mode": mode,
        "page_size": PAGE_SIZE,
        "auto_translate": False,  # 원문 그대로 (영어 paper 이라)
    }
    try:
        resp = await client.post(SEARCH_API, json=body, headers=headers, timeout=120)
        resp.raise_for_status()
        return [r["source_id"] for r in resp.json().get("results", [])]
    except Exception as e:
        log.warning("    search %s failed: %s", mode, type(e).__name__)
        return []


def compute_metrics(retrieved: list[str], expected: set[str]) -> dict:
    """단일 query 의 메트릭."""
    if not retrieved or not expected:
        return {"recall_at_10": 0, "recall_at_20": 0, "recall_at_50": 0,
                "hit_at_10": 0, "mrr": 0.0, "n_expected": len(expected),
                "n_found_at_50": 0}
    retrieved_set = set(retrieved)
    n_expected = len(expected)
    return {
        "n_expected": n_expected,
        "n_found_at_50": len(retrieved_set & expected),
        "recall_at_10": len(set(retrieved[:10]) & expected) / n_expected,
        "recall_at_20": len(set(retrieved[:20]) & expected) / n_expected,
        "recall_at_50": len(retrieved_set & expected) / n_expected,
        "hit_at_10": int(bool(set(retrieved[:10]) & expected)),
        "mrr": next((1.0 / (i + 1) for i, r in enumerate(retrieved) if r in expected), 0.0),
    }


async def main():
    t0 = time.perf_counter()
    log.info("PubMed Reproducibility Benchmark 시작")
    api_key = os.environ.get("NCBI_EUTILS_API_KEY")
    random.seed(RANDOM_SEED)

    # Step 1: sample PMIDs
    conn = await asyncpg.connect(_pg_dsn())
    try:
        candidates = await sample_test_queries(conn)
    finally:
        await conn.close()

    # Step 2: fetch abstracts
    abstracts = await fetch_pubmed_abstracts(candidates, api_key)

    # Filter: keep only those with abstract fetched
    eval_queries = []
    for c in candidates:
        if c["pmid"] in abstracts and len(eval_queries) < N_SAMPLE:
            eval_queries.append({
                "pmid": c["pmid"],
                "expected_geos": c["expected_geos"],
                "title": abstracts[c["pmid"]]["title"],
                "abstract": abstracts[c["pmid"]]["abstract"],
            })
    log.info("  eval set: %d queries (target %d)", len(eval_queries), N_SAMPLE)

    # Step 3: run search per mode + per query
    log.info("running search %d query × %d modes = %d calls", len(eval_queries), len(MODES), len(eval_queries) * len(MODES))
    per_query_results: dict[str, list[dict]] = {m: [] for m in MODES}
    async with httpx.AsyncClient(timeout=180.0) as client:
        for idx, eq in enumerate(eval_queries):
            # query = title + abstract (truncate to 2000 chars to avoid token limits)
            query_text = f"{eq['title']}\n\n{eq['abstract']}"[:2000]
            expected = set(eq["expected_geos"])
            for mode in MODES:
                retrieved = await run_search(client, query_text, mode)
                metrics = compute_metrics(retrieved, expected)
                per_query_results[mode].append({
                    "pmid": eq["pmid"],
                    "n_expected": metrics["n_expected"],
                    **metrics,
                    "top10": retrieved[:10],
                })
            if (idx + 1) % 20 == 0:
                log.info("  progress %d/%d (%.0f%%)", idx + 1, len(eval_queries),
                         100 * (idx + 1) / len(eval_queries))

    # Step 4: aggregate
    log.info("aggregating metrics…")
    summaries: dict[str, dict] = {}
    for mode in MODES:
        results = per_query_results[mode]
        summaries[mode] = {
            "n_queries": len(results),
            "mean_recall_at_10": round(statistics.mean(r["recall_at_10"] for r in results), 3),
            "mean_recall_at_20": round(statistics.mean(r["recall_at_20"] for r in results), 3),
            "mean_recall_at_50": round(statistics.mean(r["recall_at_50"] for r in results), 3),
            "mean_hit_at_10": round(statistics.mean(r["hit_at_10"] for r in results), 3),
            "mrr": round(statistics.mean(r["mrr"] for r in results), 3),
        }

    elapsed = time.perf_counter() - t0
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "elapsed_s": round(elapsed, 1),
        "config": {
            "n_sample": N_SAMPLE,
            "geo_range": list(GEO_RANGE),
            "page_size": PAGE_SIZE,
            "modes": MODES,
            "random_seed": RANDOM_SEED,
        },
        "n_eval_queries": len(eval_queries),
        "summaries": summaries,
        "per_query": per_query_results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    log.info("=" * 70)
    log.info("✅ PubMed Reproducibility Benchmark complete in %.0fs", elapsed)
    log.info(f"  n_queries: {len(eval_queries)}")
    log.info(f"  {'mode':<14} {'Recall@10':>10} {'Recall@20':>10} {'Recall@50':>10} {'Hit@10':>8} {'MRR':>8}")
    log.info("  " + "-" * 64)
    for mode in MODES:
        s = summaries[mode]
        log.info(f"  {mode:<14} {s['mean_recall_at_10']:>10} {s['mean_recall_at_20']:>10} {s['mean_recall_at_50']:>10} {s['mean_hit_at_10']:>8} {s['mrr']:>8}")
    log.info(f"\n  report → {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
