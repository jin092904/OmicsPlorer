# OmicsPlorer

OmicsPlorer is a self-hostable application for collecting public omics-dataset metadata and searching it through a web interface. The repository contains the application source, data-ingestion workers, search services, and a local-LLM integration. It does not contain the production corpus, private user data, model weights, service credentials, or the frozen evaluation outputs used in a manuscript.

## What is included

| Area | Location | Role |
|---|---|---|
| Web application | `apps/web` | Search, filtering, dataset inspection, and saved-item UI |
| API | `apps/api` | Search orchestration, metadata endpoints, and application services |
| Workers | `apps/workers` | Public-source harvesting, metadata extraction, ontology mapping, and indexing |
| Infrastructure | `infra` | Container definitions, local Compose stack, and static policy checks |
| Shared packages | `packages` | Shared schemas and small security-test fixtures |

The current implementation combines lexical search, vector retrieval, and optional reranking. Local Ollama endpoints are used for model-backed functions. Whether a particular model or index is suitable depends on the corpus, hardware, and evaluation protocol; this repository does not claim a fixed response time, accuracy, or service-level guarantee.

## Local demo

Prerequisites are Docker with Compose, enough local storage for the selected images and models, and a host that can run the configured services.

```bash
cp infra/compose/.env.example infra/compose/.env
# Replace both database password placeholders with distinct local values.
make docker-validate
make docker-demo
```

The demo inserts twelve synthetic metadata records. It is intended to check the application path, not to measure retrieval quality or production latency. See [`docs/runbooks/docker-deployment.md`](docs/runbooks/docker-deployment.md) for the supported commands and boundaries.

## Reproducibility material

Manuscript-specific protocols, frozen query sets, result tables, and figure-generation inputs belong in the separate [omicsplorer-reproducibility](https://github.com/jin092904/omicsplorer-reproducibility) repository. Keeping those artifacts separate distinguishes the versioned scientific evaluation from the evolving product source.

## Evidence and versioning

- Dependency lockfiles record the application dependency resolution used by this source snapshot.
- External services and model artifacts can change independently; record their versions, retrieval dates, and hashes for each evaluation.
- Report end-to-end user-observed latency with the corpus size, cache state, hardware, concurrency, timeout policy, and summary statistics. Do not infer production latency from one API timing or a synthetic demo.
- Do not treat planned thresholds, manual spot checks, or unexecuted CI jobs as results.
- Review the documented dependency-audit exception before deploying this snapshot.

The detailed publication boundary is in [`docs/publication-boundary.md`](docs/publication-boundary.md).

The current audit exception and its review condition are recorded in [`docs/dependency-audit-exceptions.md`](docs/dependency-audit-exceptions.md).

## Security

Do not commit `.env` files, database snapshots, user queries, credentials, or generated production data. Please report suspected vulnerabilities through GitHub's private vulnerability reporting flow described in [`SECURITY.md`](SECURITY.md).

## License and citation

The source is available under the GNU Affero General Public License v3.0 or later. The `private: true` field in `apps/web/package.json` only prevents accidental publication to the npm registry; it does not change the source license.

Organizations that cannot use the AGPL terms may request a separate commercial license as described in [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md). Citation metadata is provided in [`CITATION.cff`](CITATION.cff).
