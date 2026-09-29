# Docker deployment runbook

The canonical local configuration is `infra/compose/docker-compose.yml`. It is a reference environment for development and reproducibility checks, not a claim that the stack is production-ready for a particular institution.

## Prepare configuration

```bash
cp infra/compose/.env.example infra/compose/.env
```

Replace `POSTGRES_PASSWORD` and `APP_DB_PASSWORD` with different local values. The scripts intentionally stop if the `.env` file is missing. Do not commit it.

Validate the resolved configuration before starting containers:

```bash
make docker-validate
```

## Run the real-data GEO demo

```bash
make docker-demo-geo
```

The command runs these steps in order:

1. It checks the SHA-256 checksum of `infra/compose/demo-geo/omicsplorer-demo-geo-v1.jsonl.gz`
   against its manifest.
2. It builds the images, starts the stores, and applies the database migrations.
3. It downloads `qwen3-embedding:8b` into the Ollama volume and compares the downloaded build with
   the one recorded in the manifest. If the builds differ, it prints a warning and continues.
4. It downloads `Qwen/Qwen3-Reranker-0.6B` at the revision pinned in
   `apps/api/src/services/reranker.py` into the `hf_cache` volume, then loads it once.
5. It loads the 5,000 records (`demo-geo-load`). Titles and summaries come from NCBI E-utilities,
   and the stored vectors are written to Qdrant. Set `NCBI_API_KEY` in `.env` to use NCBI's
   higher request limit.
6. It builds the lexical index (`demo-geo-index`).
7. It starts the API and web containers and runs one search with the GEO source filter. The
   search prints the retrieval components and candidate counts. The command stops with an error
   unless lexical retrieval, vector retrieval, and reranking all contributed.

Running the command again updates the demo rows in place. The loader never overwrites a row that
it did not create. To verify a search by hand:

```bash
curl -fsS -H 'Content-Type: application/json' -H 'X-Eval-Mode: 1' \
  -d '{"query_text": "Single-cell RNA sequencing of Alzheimer disease microglia", "page_size": 10}' \
  http://127.0.0.1:8000/api/v1/search | python3 -c 'import json,sys; t=json.load(sys.stdin)["evaluation_trace"]; print(t["effective_mode"], t["components"], t["candidate_counts"])'
```

The `components` entries for lexical, dense, and reranker should all be `used`, and both
`candidate_counts` should be above zero. The trace also lists `configuration_missing_or_invalid`
under `fallbacks`. That entry only means that no frozen-evaluation configuration file is mounted,
and it does not affect search.

## Run the synthetic demo

```bash
make docker-demo
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:3000/
```

The demo seed contains twelve synthetic records marked with `source_db=DEMO` and `raw_metadata.demo=true`. It builds a lexical index so the application path can be inspected without first downloading an embedding model. It is not a retrieval benchmark and does not represent a production corpus.

## Common commands

```bash
make dev             # build and start the default stack
make docker-demo-geo # real-data GEO demo (see above)
make docker-models   # download the embedding model and the reranker
make docker-ingest   # start harvesting worker and scheduler profiles
make docker-sol4-shadow  # run the maintenance path without dataset DB writes
make ps
make logs
make down
```

`make docker-ingest` can modify the local database by collecting metadata from configured public services. Review current API terms, configure contact information and rate limits, and make a backup before using it against a valued database.

The `sol4-commit` Compose profile enables a maintenance command that writes extracted metadata. It has no Makefile shortcut and should be invoked only after reviewing a shadow run and backing up the database.

## Models and resources

The default configuration uses one Ollama endpoint for embeddings. The reranker runs inside the API
container and reads its weights from the `hf_cache` volume. `make docker-models` fills that volume,
and without it the API tries to download the weights at the first search. The default reranker is
`Qwen/Qwen3-Reranker-0.6B` at a pinned Hugging Face revision. If you set `RERANKER_MODEL` to
another model, also set `RERANKER_REVISION` or leave it blank. Model downloads, memory use, warm-up
time, and inference latency depend on the selected model and host. The image and model identifiers
used in a manuscript run must be recorded separately from this runbook.

## Lexical index mapping

Source and facet filters (`source_db`, `modality`, `disease_ids`, `tissue_ids`, `cell_type_ids`,
and others) use exact-match `term` queries. They only work when the OpenSearch index maps these
fields as `keyword`, as defined in `apps/workers/src/indexer/lexical.py`. If an index is created
implicitly, for example because a document was written before the index existed, OpenSearch maps
them as analyzed `text`. Every filtered lexical query then returns nothing, while vector search
still answers.

`ensure_index` now stops with `LexicalIndexMappingError` when it finds such an index. To rebuild it
with the expected mapping, run:

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.yml \
  --profile demo-geo run --rm demo-geo-index scripts/reindex_lexical.py --recreate
```

For a full corpus, run the same script through the maintenance service:

```bash
docker compose --env-file infra/compose/.env -f infra/compose/docker-compose.yml \
  --profile maintenance run --rm reindex-all scripts/reindex_lexical.py --recreate
```

Lexical search is empty until the rebuild finishes.

Large corpora, database snapshots, search-index snapshots, and model blobs are intentionally excluded from Git. Restore them using the database or index vendor's supported snapshot mechanism; never bind-mount a live production data directory into this local stack.

The reference Compose file pins PostgreSQL 18 and mounts its named volume at
`/var/lib/postgresql`, which is the data-volume target used by the official
PostgreSQL 18 image. Do not attach a PostgreSQL 17-or-earlier data volume to this
service and expect an in-place upgrade. Use PostgreSQL's supported dump/restore
or `pg_upgrade` procedure and verify a backup before changing major versions.

## Production boundary

Before exposing any service beyond loopback, independently configure and test:

- authentication and authorization;
- TLS and trusted reverse-proxy settings;
- firewall and service-to-service network policy;
- secret storage and rotation;
- backups, restore drills, retention, and deletion;
- monitoring and incident response;
- privacy, data-source licensing, and institutional requirements.

No uptime, response-time, security-certification, or support commitment is provided by the reference configuration.

## Reporting performance

For interactive search, measure from browser submission to the defined UI event, such as first result displayed and final result settled. Record the source commit, corpus size, index state, query set, hardware, model, concurrency, warm-up/cache policy, timeout, failures, repetitions, and summary statistics such as median and tail percentiles.

Do not replace an end-to-end measurement with an internal API timer or the fastest observed request. Runs that time out must remain visible in the reported protocol and results.
