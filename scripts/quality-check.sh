#!/usr/bin/env bash
# quality-check.sh — 라이브 API 검색 품질/속도 점검. 카테고리별 top-3 + 속도.
set -uo pipefail
API="http://localhost:8000/api/v1/search"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

body(){ python3 -c 'import json,sys;print(json.dumps({"query_text":sys.argv[1],"mode":"rrf_rerank","corpus":"production"}))' "$1"; }

run(){  # $1=label $2=query
  local f="$TMP/r.json"
  local wall
  wall=$(curl -s --max-time 180 -o "$f" -w '%{time_total}' -X POST "$API" \
    -H 'Content-Type: application/json' -H 'X-Eval-Mode: 1' -d "$(body "$2")")
  echo "── [$1] «$2»"
  python3 - "$f" "$wall" <<'PY'
import json,sys
f,wall=sys.argv[1],sys.argv[2]
try:
    d=json.load(open(f))
except Exception as e:
    print(f"   PARSE FAIL: {e}"); sys.exit()
r=d.get("results",[])
print(f"   server={d.get('latency_ms')}ms wall={float(wall):.2f}s  total={d.get('total_estimated')}  n={len(r)}")
tq=d.get("translated_query")
if tq: print(f"   translated: {d.get('original_query')} -> {tq}")
for i,x in enumerate(r[:3]):
    sb=x.get("score_breakdown") or {}
    sc=x.get("score")
    mod=",".join(x.get("modality") or [])[:30]
    print(f"   {i+1}. [{x.get('source_id')}] score={sc:.3f} mod=[{mod}] n={x.get('n_samples')}")
    print(f"      {(x.get('title') or '')[:90]}")
PY
}

echo "==================== SPEED WARMUP ===================="
run warmup "single cell pancreas"

echo "==================== 0. OPENING (안전) ===================="
run opening "single-cell RNA-seq of human pancreatic islets"

echo "==================== 1. HYBRID (의미+키워드) ===================="
run hybrid "tumor immune microenvironment"

echo "==================== 2. ABBREVIATION (약어) ===================="
run nsclc "NSCLC scRNA-seq"
run hcc "PBMC from HCC patients"
run copd "COPD lung tissue RNA-seq"

echo "==================== 3. COMPOUND / PAIRED (복합) ===================="
run urine_stool "paired urine and stool microbiome from bladder cancer patients"
run kidney_liver "multi-tissue RNA-seq of kidney and liver"
run synovial_blood "scRNA-seq of matched immune cells from synovial fluid and peripheral blood in rheumatoid arthritis"

echo "==================== 4. NEGATION (부정/제외) ===================="
run negation "lung tissue RNA-seq without any smoking history"

echo "==================== 5. ACCESSION LOOKUP (정확 ID) ===================="
run accession "GSE160241"

echo "==================== 6. KOREAN PARITY (한국어) ===================="
run ko_panc "사람 췌장 섬세포 단일세포 RNA-seq"
run ko_tme "종양 면역 미세환경"
run ko_nsclc "비소세포폐암 단일세포 RNA 시퀀싱"

echo "==================== 7. KNOWN-WEAK (검증용) ===================="
run cesc "CESC scRNA-seq"
run multiomics "CITE-seq and TCR-seq of tumor infiltrating lymphocytes"

echo "==================== DONE ===================="