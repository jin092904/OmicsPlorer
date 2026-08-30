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
