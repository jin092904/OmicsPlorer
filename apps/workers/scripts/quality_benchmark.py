"""Search quality benchmark — facet-based automatic relevance scoring.

검색 결과의 modality/disease/tissue/cell_type/library_strategy 가 query 의도 (expected facets)
와 매칭되는지 자동 채점. LLM 호출 없음, 30분 안에 종료.

Metrics:
  - facet_precision@10  = (top10 중 expected facet 하나 이상 일치) / 10
  - facet_hit@1         = top1 일치 여부 (0 또는 1)
  - exact_match         = source_id 정확 일치 시 1 (accession lookup)
  - mean_reciprocal_rank (MRR) for first relevant
  - 4 mode 비교: bm25_only / dense_only / rrf / rrf_rerank

쿼리 셋 (15 쿼리, 영문/한글 mix):
  - 다양한 modality (scRNA-seq, ChIP-seq, methylation, microarray, Hi-C, 16S 등)
  - 다양한 disease/tissue
  - 한국어 변형 3건
  - accession lookup 1건
"""
from __future__ import annotations

import asyncio
import json
import statistics
from pathlib import Path

import httpx

API = "http://localhost:8000/api/v1/search"
REPORT = Path("/tmp/genofinder-quality-benchmark.json")

# (qid, query_text, expected_facets, intent_note)
# expected_facets 형식:
#   - modality: 일치해야 할 modality string set (any 매치)
#   - tissue_contains: tissue label substring (UBERON ID 매칭 어려우니 키워드 기반)
#   - disease_contains: disease label substring
#   - exact_source_id: accession 룩업
EVAL_QUERIES = [
    {
        "qid": "lung_scrna",
        "query": "lung adenocarcinoma single cell RNA-seq",
        "modality": {"scRNA-seq"},
        "title_contains": {"lung", "adenocarcin", "single", "scrna"},
    },
    {
        "qid": "breast_methylation",
        "query": "breast cancer methylation",
        "modality": {"methylation", "microarray"},
        "title_contains": {"breast", "methylation"},
    },
    {
        "qid": "alzheimer_brain",
        "query": "Alzheimer disease brain transcriptome",
        "modality": {"bulk RNA-seq", "scRNA-seq", "microarray"},
        "title_contains": {"alzheim", "brain", "transcript"},
    },
    {
        "qid": "atac_prostate",
        "query": "ATAC-seq prostate",
        "modality": {"ATAC-seq", "scATAC-seq"},
        "title_contains": {"atac", "prostate"},
    },
    {
        "qid": "chipseq_liver",
        "query": "ChIP-seq H3K27ac liver",
        "modality": {"ChIP-seq"},
        "title_contains": {"chip", "liver", "h3k27"},
    },
    {
        "qid": "pancreas_islet",
        "query": "single cell pancreatic islet",
        "modality": {"scRNA-seq"},
        "title_contains": {"pancrea", "islet", "single"},
    },
    {
        "qid": "covid_lung",
        "query": "COVID-19 lung pathology",
        "title_contains": {"covid", "sars-cov", "lung"},
    },
    {
        "qid": "tcr_repertoire",
        "query": "T cell receptor repertoire profiling",
        "title_contains": {"t cell receptor", "tcr", "repertoire"},
    },
    {
        "qid": "microbiome_16s",
        "query": "16S rRNA microbiome gut",
        "modality": {"16S", "amplicon"},
        "title_contains": {"16s", "microb", "gut"},
    },
    {
        "qid": "hic_chromatin",
        "query": "Hi-C chromatin 3D organization",
        "modality": {"Hi-C"},
        "title_contains": {"hi-c", "chromatin", "3d"},
    },
    {
        "qid": "spatial_melanoma",
        "query": "spatial transcriptomics melanoma",
        "modality": {"spatial"},
        "title_contains": {"spatial", "melanoma"},
    },
    {
        "qid": "longread_pacbio",
        "query": "long read Nanopore PacBio genome",
        "modality": {"long-read"},
        "title_contains": {"long-read", "long read", "nanopore", "pacbio"},
    },
    {
        "qid": "accession_lookup",
        "query": "GSE131907",
        "exact_source_id": "GSE131907",
    },
    {
        "qid": "ko_lung_scrna",
        "query": "폐선암 단일세포",
        "modality": {"scRNA-seq"},
        "title_contains": {"lung", "single"},
    },
    {
        "qid": "ko_breast_meth",
        "query": "유방암 메틸레이션",
        "modality": {"methylation", "microarray"},
        "title_contains": {"breast", "methylation"},
    },
]

MODES = ["bm25_only", "dense_only", "rrf", "rrf_rerank"]


def score_result(result: dict, expected: dict) -> dict:
    """단일 결과의 매칭 신호 추출."""
    hits = {"modality": 0, "title": 0, "exact": 0}
    # modality 매칭
    if "modality" in expected:
        for m in result.get("modality", []) or []:
            if m in expected["modality"]:
                hits["modality"] = 1
                break
    # title substring 매칭
    if "title_contains" in expected:
        title = (result.get("title") or "").lower()
        abstract = (result.get("abstract_snippet") or "").lower()
        text = title + " " + abstract
        for needle in expected["title_contains"]:
            if needle.lower() in text:
                hits["title"] = 1
                break
    # exact source_id
    if "exact_source_id" in expected:
        if result.get("source_id") == expected["exact_source_id"]:
            hits["exact"] = 1
    # 결과 적합성: modality OR title OR exact 중 하나라도 hit
    is_relevant = max(hits.values()) > 0
    return {"hits": hits, "is_relevant": is_relevant}


async def call_search(client, query_text, mode):
    headers = {"Content-Type": "application/json"}
    if mode != "rrf_rerank":
        headers["X-Eval-Mode"] = "1"
    body = {"query_text": query_text, "page_size": 10, "mode": mode}
    try:
        resp = await client.post(API, json=body, headers=headers, timeout=180)
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


async def evaluate_mode(client, mode: str) -> dict:
    print(f"\n=== mode: {mode} ===")
    per_query: list[dict] = []
    for q in EVAL_QUERIES:
        data = await call_search(client, q["query"], mode)
        if not data:
            per_query.append({"qid": q["qid"], "error": True})
            continue
        results = data.get("results", [])
        scored = [score_result(r, q) for r in results]
        relevant_flags = [s["is_relevant"] for s in scored]
        p_at_10 = sum(relevant_flags) / 10 if results else 0
        hit_at_1 = relevant_flags[0] if relevant_flags else 0
        first_rel = next((i + 1 for i, r in enumerate(relevant_flags) if r), None)
        rr = (1.0 / first_rel) if first_rel else 0.0
        per_query.append({
            "qid": q["qid"],
            "query": q["query"],
            "n_results": len(results),
            "n_relevant_top10": sum(relevant_flags),
            "precision_at_10": round(p_at_10, 3),
            "hit_at_1": hit_at_1,
            "rr": round(rr, 3),
            "modality_hits": sum(s["hits"]["modality"] for s in scored),
            "title_hits": sum(s["hits"]["title"] for s in scored),
            "top1_source_id": results[0]["source_id"] if results else None,
            "top1_title": (results[0].get("title") or "")[:80] if results else None,
        })
        print(f"  {q['qid']:<22} P@10={p_at_10:.2f}  hit@1={hit_at_1}  RR={rr:.3f}  top1={(results[0]['source_id'] if results else 'NONE')}")
    # 집계
    p10s = [pq["precision_at_10"] for pq in per_query if "error" not in pq]
    h1s = [pq["hit_at_1"] for pq in per_query if "error" not in pq]
    rrs = [pq["rr"] for pq in per_query if "error" not in pq]
    return {
        "mode": mode,
        "n_queries": len(per_query),
        "mean_precision_at_10": round(statistics.mean(p10s), 3) if p10s else 0,
        "mean_hit_at_1": round(statistics.mean(h1s), 3) if h1s else 0,
        "mrr": round(statistics.mean(rrs), 3) if rrs else 0,
        "per_query": per_query,
    }


async def main():
    print(f"quality benchmark — {len(EVAL_QUERIES)} queries × {len(MODES)} modes")
    summaries: dict = {}
    async with httpx.AsyncClient() as client:
        # health check
        h = await client.get("http://localhost:8000/api/v1/health")
        assert h.status_code == 200, "API down"
        for mode in MODES:
            summaries[mode] = await evaluate_mode(client, mode)

    REPORT.write_text(json.dumps(summaries, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print("✅ quality benchmark complete")
    print("=" * 70)
    print(f"{'mode':<14} {'P@10':>8} {'Hit@1':>8} {'MRR':>8}")
    print("-" * 70)
    for mode in MODES:
        s = summaries[mode]
        print(f"{mode:<14} {s['mean_precision_at_10']:>8.3f} {s['mean_hit_at_1']:>8.3f} {s['mrr']:>8.3f}")
    print(f"\nreport → {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
