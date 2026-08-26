# Architecture

OmicsPlorer is organized as a monorepo with three application layers and a local service stack.

```text
public metadata sources
        |
        v
workers: harvest -> normalize/extract -> ontology mapping -> index
        |                                      |
        v                                      v
 PostgreSQL                              Qdrant / OpenSearch
        \                                      /
         +-------------- API ----------------+
                           |
                           v
                       web client
```

## Responsibilities

- `apps/workers` contains source-specific harvesters, scheduled jobs, metadata extraction, ontology mapping, and search-index updates.
- `apps/api` reads structured metadata and search indexes, coordinates lexical/vector retrieval and optional reranking, and exposes application endpoints.
- `apps/web` is a Next.js interface for queries, filters, result inspection, and user-facing workflows.
- PostgreSQL stores normalized metadata and application state. Qdrant stores vector-search payloads and OpenSearch supports lexical retrieval.
- Ollama provides local model endpoints. Model names are configuration values, and model availability is a deployment prerequisite rather than a property guaranteed by this repository.

## Data flow boundaries

The repository contains collectors and schema migrations, but not a production corpus. Source availability, API limits, record counts, and metadata fields can change. Each scientific evaluation therefore needs a frozen corpus manifest or snapshot reference in the reproducibility repository.

The default Compose ports bind to loopback. That reduces accidental local exposure but is not a production security architecture. Authentication, network controls, TLS, backups, and secrets management must be selected and validated for the deployment environment.

## Search interpretation

Search behavior depends on the indexed corpus, language, filters, selected embedding and reranking models, model warm-up, cache state, and available hardware. Any comparison must keep those factors fixed or report them explicitly. The code structure alone does not establish superiority over another search service.
