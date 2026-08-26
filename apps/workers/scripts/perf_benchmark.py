"""Performance benchmark — post-upgrade + post-PubMed-augment 상태.

측정:
  1. Search latency by mode (bm25_only / dense_only / rrf / rrf_rerank)
     - 각 mode × 6 query × 5 회 = 120 호출
     - cold (첫 호출) + warm (이후) 분리
  2. Throughput — concurrent 10 query
  3. Storage 비교

쿼리 셋: 영어 + 한국어 + accession 룩업.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

API = "http://localhost:8000/api/v1/search"
REPORT = Path("/tmp/genofinder-perf-benchmark.json")

QUERIES = [
    ("en_general", "lung cancer single cell RNA-seq"),
    ("en_specific", "breast cancer methylation array"),
    ("en_disease", "Alzheimer brain transcriptome aging"),
    ("ko_short", "폐암 단일세포 RNA"),
    ("ko_long", "스트레스 마우스 면역세포 발현 변화"),
    ("accession", "GSE131907"),
]

MODES = ["bm25_only", "dense_only", "rrf", "rrf_rerank"]


async def call_search(client, query_text, mode, eval_header):
    headers = {"Content-Type": "application/json"}
    if eval_header:
        headers["X-Eval-Mode"] = "1"
    body = {"query_text": query_text, "page_size": 10, "mode": mode}
    t0 = time.perf_counter()
    try:
        resp = await client.post(API, json=body, headers=headers, timeout=180)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "elapsed_ms": elapsed_ms}
        d = resp.json()
        return {
            "client_ms": elapsed_ms,
            "server_ms": d["latency_ms"],
            "total": d["total_estimated"],
            "n_results": len(d["results"]),
        }
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {"error": str(e), "elapsed_ms": elapsed_ms}


async def measure_mode(client, mode):
    """Cold + 4 warm 호출. 6 쿼리 × 5 = 30 호출."""
    eval_header = mode != "rrf_rerank"
    print(f"\n=== mode: {mode} (eval_header={eval_header}) ===")
    rows = []
    for qid, qtext in QUERIES:
        for i in range(5):
            r = await call_search(client, qtext, mode, eval_header)
            phase = "cold" if i == 0 else "warm"
            rows.append({
                "query_id": qid, "query": qtext, "iter": i, "phase": phase, **r,
            })
            print(f"  {qid:<14} #{i} {phase:<4} client={r.get('client_ms', 0):>7.0f}ms  server={r.get('server_ms', 0):>6}ms  results={r.get('n_results', 0)}")
    return rows


def summarize(rows, mode):
    warm = [r for r in rows if r["phase"] == "warm" and "server_ms" in r]
    cold = [r for r in rows if r["phase"] == "cold" and "server_ms" in r]
    if not warm:
        return {"mode": mode, "error": "no successful runs"}
    warm_lat = [r["server_ms"] for r in warm]
    return {
        "mode": mode,
        "cold_mean_ms": statistics.mean([r["server_ms"] for r in cold]) if cold else None,
        "cold_max_ms": max([r["server_ms"] for r in cold]) if cold else None,
        "warm_n": len(warm_lat),
        "warm_mean_ms": round(statistics.mean(warm_lat), 1),
        "warm_median_ms": round(statistics.median(warm_lat), 1),
        "warm_p95_ms": round(sorted(warm_lat)[int(len(warm_lat)*0.95)], 1) if len(warm_lat) > 1 else warm_lat[0],
        "warm_min_ms": min(warm_lat),
        "warm_max_ms": max(warm_lat),
    }


async def measure_throughput(client, n_concurrent=10):
    print(f"\n=== throughput: {n_concurrent} concurrent rrf_rerank ===")
    # Warm up first
    await call_search(client, "lung cancer scRNA", "rrf_rerank", False)

    t0 = time.perf_counter()
    tasks = [
        call_search(client, q[1], "rrf_rerank", False) for q in QUERIES[:n_concurrent]
    ]
    # If we have fewer queries than n_concurrent, pad with repeats
    if len(tasks) < n_concurrent:
        tasks += [call_search(client, QUERIES[0][1], "rrf_rerank", False)
                  for _ in range(n_concurrent - len(tasks))]
    results = await asyncio.gather(*tasks)
    elapsed = (time.perf_counter() - t0) * 1000
    successes = [r for r in results if "server_ms" in r]
    return {
        "concurrent": n_concurrent,
        "total_wall_ms": round(elapsed, 1),
        "throughput_req_per_s": round(n_concurrent / (elapsed / 1000), 2),
        "successes": len(successes),
        "failures": len(results) - len(successes),
        "mean_server_ms": round(statistics.mean([r["server_ms"] for r in successes]), 1) if successes else None,
    }


async def main():
    async with httpx.AsyncClient() as client:
        # Health check
        h = await client.get("http://localhost:8000/api/v1/health")
        assert h.status_code == 200, f"API down: {h.status_code}"
        print("API healthy")

        all_rows = {}
        summaries = {}
        for mode in MODES:
            rows = await measure_mode(client, mode)
            all_rows[mode] = rows
            summaries[mode] = summarize(rows, mode)

        throughput = await measure_throughput(client, n_concurrent=10)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary_by_mode": summaries,
        "throughput": throughput,
        "raw_rows": all_rows,
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print("\n" + "=" * 70)
    print("✅ benchmark complete")
    print("=" * 70)
    print(f"{'mode':<14} {'cold_max':>10} {'warm_mean':>10} {'warm_p95':>10} {'warm_min':>10}")
    print("-" * 70)
    for mode in MODES:
        s = summaries[mode]
        print(f"{mode:<14} {s.get('cold_max_ms', 'n/a'):>10} {s.get('warm_mean_ms', 'n/a'):>10} {s.get('warm_p95_ms', 'n/a'):>10} {s.get('warm_min_ms', 'n/a'):>10}")
    print(f"\nthroughput (10 concurrent): {throughput['throughput_req_per_s']} req/s, mean server {throughput['mean_server_ms']}ms")
    print(f"report → {REPORT}")


if __name__ == "__main__":
    asyncio.run(main())
