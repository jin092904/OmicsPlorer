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
ENV_ARGS="--env-file $ENV_FILE"

# shellcheck disable=SC2086
compose() { docker compose $ENV_ARGS -f "$BASE" "$@"; }

usage() {
  echo "Usage: $0 {validate|build|demo|up|models|ingest|sol4-shadow|down|status}"
}

case "${1:-}" in
  validate)
    compose config -q
    compose --profile demo --profile ingest --profile models --profile maintenance config -q
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
  up)
    compose up -d --build
    ;;
  models)
    compose --profile models run --rm model-pull-embed
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
