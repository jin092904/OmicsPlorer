# GPB Application Note source release

Proposed tag: `gpb-application-note-public-v1`

This tag will identify the public application-source snapshot corresponding to the separately
versioned OmicsPlorer manuscript reproducibility release. The two repositories use different
license boundaries:

- application source: AGPL-3.0-or-later, with the separately documented commercial-license route;
- manuscript evaluator and original evidence materials: MIT and CC BY 4.0 in
  `jin092904/omicsplorer-reproducibility`.

The source release does not include the production corpus, private user data, model weights,
credentials, frozen store snapshots, or the manuscript's public evaluation outputs.

Before publishing the tag:

1. merge this metadata change into protected `main` and record the final commit;
2. confirm `ci`, `security-gates`, and `docker-demo` succeed for the final source commit;
3. create an annotated `gpb-application-note-public-v1` tag without moving it later;
4. clone that tag through the public HTTPS URL and repeat the twelve-record synthetic demo;
5. publish the GitHub release and archive the exact source tag alongside the corresponding
   reproducibility tag.

The synthetic demo confirms one application path with twelve generated records. It is not a
retrieval-quality evaluation, production-latency measurement, load test, or service-level claim.

## Proposed follow-up tag: `gpb-application-note-public-v2`

`gpb-application-note-public-v1` stays unchanged. The follow-up source tag would add:

- the real-data GEO demo (`make docker-demo-geo`; data card in `infra/compose/demo-geo/README.md`);
- the reranker default `Qwen/Qwen3-Reranker-0.6B` at the recorded revision, replacing the
  `ms-marco-MiniLM` default that the v1 Compose file set, and a writable reranker cache for the
  non-root API container;
- a lexical-index mapping check (`LexicalIndexMappingError`, `reindex_lexical.py --recreate`) and
  per-retriever candidate counts in the evaluation trace.

Before publishing it:

1. merge the change into protected `main`;
2. confirm `ci`, `security-gates`, `docker-demo`, and `docker-demo-geo` succeed for the final
   commit, and copy the measured resources from the `docker-demo-geo` step summary into the README;
3. create the annotated tag without moving it later;
4. clone the tag through the public HTTPS URL and run `make docker-demo-geo`;
5. publish the GitHub release and archive the exact source tag.

The demo is a deliberately chosen 5,000-record subset for trying the search path. It is not a
retrieval-quality evaluation, production-latency measurement, or service-level claim.

