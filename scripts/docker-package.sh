#!/bin/sh
set -eu

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE="$REPO_DIR/infra/compose/docker-compose.yml"
ENV_FILE=${OMICSPLORER_ENV_FILE:-$REPO_DIR/infra/compose/.env}

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing environment file: $ENV_FILE" >&2
  echo "Copy infra/compose/.env.example to infra/compose/.env and replace the placeholders." >&2
  exit 2
fi
compose() { docker compose --env-file "$ENV_FILE" -f "$BASE" "$@"; }

DEMO_GEO_DIR="$REPO_DIR/infra/compose/demo-geo"
DEMO_GEO_ASSET="$DEMO_GEO_DIR/omicsplorer-demo-geo-v1.jsonl.gz"
DEMO_GEO_MANIFEST="$DEMO_GEO_DIR/omicsplorer-demo-geo-v1.manifest.json"

usage() {
  echo "Usage: $0 {validate|build|demo|demo-geo|up|models|ingest|sol4-shadow|down|status}"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  else
    shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

manifest_value() {
  sed -n "s/^ *\"$1\": *\"\([^\"]*\)\".*/\1/p" "$DEMO_GEO_MANIFEST" | head -n 1
}

check_demo_geo_asset() {
  if [ ! -f "$DEMO_GEO_ASSET" ] || [ ! -f "$DEMO_GEO_MANIFEST" ]; then
    echo "Missing demo data in $DEMO_GEO_DIR (expected the .jsonl.gz asset and its manifest)." >&2
    exit 2
  fi
  expected=$(manifest_value sha256)
  actual=$(sha256_of "$DEMO_GEO_ASSET")
  if [ "$expected" != "$actual" ]; then
    echo "Demo data checksum mismatch: expected $expected, got $actual" >&2
    exit 2
  fi
  echo "Demo data checksum OK ($actual)"
}

# The stored vectors come from one Ollama build; another build under the same tag embeds differently.
check_embedding_model() {
  tag=$(manifest_value ollama_tag)
  expected=$(manifest_value ollama_digest | cut -c 1-12)
  actual=$(compose exec -T ollama-embed ollama list | awk -v tag="$tag" '$1 == tag {print $2}')
  if [ "$expected" = "$actual" ]; then
    echo "Embedding model $tag matches the recorded build ($actual)"
  else
    echo "WARNING: $tag is build '${actual:-missing}', but the demo vectors were made with $expected." >&2
    echo "WARNING: search still runs, but results can differ from the recorded configuration." >&2
  fi
}

# The first search also loads the reranker; stop unless all three retrieval steps contributed.
warm_up_search() {
  if ! compose exec -T api python - <<'PY'
import json
import sys
import time
import urllib.request

body = json.dumps({"query_text": "Single-cell RNA sequencing of Alzheimer's disease microglia",
                   "page_size": 5, "source_db": ["GEO"]}).encode()
request = urllib.request.Request(
    "http://127.0.0.1:8000/api/v1/search", data=body,
    headers={"Content-Type": "application/json", "X-Eval-Mode": "1"})
started = time.monotonic()
payload = json.load(urllib.request.urlopen(request, timeout=900))
elapsed = time.monotonic() - started
trace = payload.get("evaluation_trace") or {}
components = trace.get("components") or {}
counts = trace.get("candidate_counts") or {}
print(f"First search: {elapsed:.1f} s; path {trace.get('effective_mode')}; "
      f"lexical {components.get('lexical')} ({counts.get('lexical')} candidates), "
      f"dense {components.get('dense')} ({counts.get('dense')} candidates), "
      f"reranker {components.get('reranker')}")
for item in payload.get("results", [])[:5]:
    print(" ", item.get("source_id"))
ok = (trace.get("effective_mode") == "rrf_rerank"
      and all(components.get(name) == "used" for name in ("lexical", "dense", "reranker"))
      and (counts.get("lexical") or 0) > 0 and (counts.get("dense") or 0) > 0
      and payload.get("results"))
sys.exit(0 if ok else 1)
PY
  then
    echo "The first search did not use lexical retrieval, vector retrieval, and reranking." >&2
    echo "See 'make logs' and docs/runbooks/docker-deployment.md." >&2
    exit 1
  fi
}

step() {
  STEP_START=$(date +%s)
  echo "==> $*"
}

step_done() {
  echo "    done in $(( $(date +%s) - STEP_START )) s"
}

case "${1:-}" in
  validate)
    compose config -q
    compose --profile demo --profile demo-geo --profile ingest --profile models --profile maintenance config -q
    ;;
  build)
    compose build api workers web
    ;;
  demo)
    compose build api workers web
    compose up -d postgres redis qdrant opensearch ollama-embed
    compose run --rm migrate
    compose --profile demo run --rm demo-seed
    compose --profile demo run --rm demo-index
    compose up -d api web
    echo "OmicsPlorer demo: http://localhost:${WEB_PORT:-3000}"
    ;;
  demo-geo)
    check_demo_geo_asset
    step "Build images"
    compose build api workers web
    step_done
    step "Start stores and apply migrations"
    compose up -d postgres redis qdrant opensearch ollama-embed
    compose run --rm migrate
    step_done
    step "Download the embedding model"
    compose --profile models run --rm model-pull-embed
    check_embedding_model
    step_done
    step "Download and load the reranker"
    compose --profile models run --rm model-pull-reranker
    step_done
    step "Load 5,000 GEO Series (titles and summaries from NCBI)"
    compose --profile demo-geo run --rm demo-geo-load
    step_done
    step "Build the lexical index"
    compose --profile demo-geo run --rm demo-geo-index
    step_done
    step "Start the API and web application"
    compose up -d --wait api web
    step_done
    step "Run the first search"
    warm_up_search
    step_done
    echo "OmicsPlorer GEO demo: http://localhost:${WEB_PORT:-3000}"
    ;;
  up)
    compose up -d --build
    ;;
  models)
    compose --profile models run --rm model-pull-embed
    compose --profile models run --rm model-pull-reranker
    ;;
  ingest)
    compose --profile ingest up -d workers beat
    ;;
  sol4-shadow)
    compose --profile maintenance run --rm sol4-shadow
    ;;
  down)
    compose down
    ;;
  status)
    compose ps
    ;;
  *)
    usage
    exit 2
    ;;
esac
