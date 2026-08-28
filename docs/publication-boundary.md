# Publication and reproducibility boundary

This repository is the evolving application source. The separate reproducibility repository is the frozen scientific record for a manuscript.

## Included here

- API, web, worker, indexing, and local-LLM integration source
- Schema migrations and synthetic demo seed
- Dependency lockfiles and container definitions
- Operational instructions that apply to the published source snapshot

## Kept in the reproducibility repository

- Preregistered or frozen evaluation protocols
- Query sets and relevance judgments approved for redistribution
- Raw run logs after privacy and license review
- Aggregated result tables, statistical analysis, and figure-generation inputs
- A manifest linking an evaluation to an exact source commit, configuration, corpus snapshot, and model identifiers

The application exposes a per-request effective-path trace only when the caller
sets `X-Eval-Mode: 1`. A frozen deployment must mount its completed canonical
server configuration and set `EFFECTIVE_SERVER_CONFIG_PATH`; a missing or
unreadable file produces no eligible configuration digest. The trace contract
and CI success are implementation evidence, not proof that a particular live
deployment or frozen run used that path.

## Not published by default

- Credentials and `.env` files
- User queries, click logs, account data, or other personal information
- Production database and search-index snapshots
- Third-party raw data or model weights without confirmed redistribution rights
- Local paths, machine inventories, and operational details that are unnecessary for reproduction

## Claim rule

A number belongs in the manuscript only when its measurement unit, dataset/corpus, sample size, hardware, software revision, cache/warm-up condition, timeout and failure handling, and aggregation statistic are recorded. Planned thresholds and synthetic-demo observations are not manuscript results.
