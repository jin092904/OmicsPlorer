# Third-party components and data

The application depends on third-party libraries, container images, public metadata services, ontologies, and model runtimes. Their licenses and terms are not replaced by the OmicsPlorer license.

- Python and JavaScript dependencies are enumerated in the project manifests and lockfiles.
- Container image references are declared in `infra/docker` and `infra/compose`.
- Public metadata service endpoints used by harvesters are listed in `docs/external-apis.md`.
- Model weights are downloaded separately and remain subject to the model publisher's license.
- Public metadata can still carry attribution, access, rate-limit, or redistribution conditions. Review the source database's current terms before collecting or redistributing it.
- Generated ontology label snapshots are intentionally not committed until their ontology versions, retrieval date, and redistribution terms are recorded.

This file is an inventory guide, not a complete legal determination. A release should include a dependency and data-license review for the exact artifacts distributed with it.
