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
make docker-models   # download the configured embedding model
make docker-ingest   # start harvesting worker and scheduler profiles
make docker-sol4-shadow  # run the maintenance path without dataset DB writes
make ps
make logs
make down
```

`make docker-ingest` can modify the local database by collecting metadata from configured public services. Review current API terms, configure contact information and rate limits, and make a backup before using it against a valued database.

The `sol4-commit` Compose profile enables a maintenance command that writes extracted metadata. It has no Makefile shortcut and should be invoked only after reviewing a shadow run and backing up the database.

## Models and resources

The default configuration uses one Ollama endpoint. Model downloads, memory use, warm-up time, and inference latency depend on the selected model and host. The image and model identifiers used in a manuscript run must be recorded separately from this runbook.

Large corpora, database snapshots, search-index snapshots, and model blobs are intentionally excluded from Git. Restore them using the database or index vendor's supported snapshot mechanism; never bind-mount a live production data directory into this local stack.

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
