# Dependency-audit exceptions

An audit exception is not a statement that a vulnerability is harmless. It records a known unresolved finding so that CI does not silently pass or fail without context.

## PYSEC-2026-3447 — setuptools

| Field | Record |
|---|---|
| Recorded | 2026-08-26 |
| Affected environment | `apps/api` lockfile |
| Dependency path | `omicsplorer-api` -> `torch==2.11.0+cpu` -> `setuptools==81.0.0` |
| Audit fix floor | `setuptools>=83.0.0` |
| Resolver constraint | The selected PyTorch build requires `setuptools<82` |
| CI handling | `pip-audit --ignore-vuln PYSEC-2026-3447` for this ID only |

The resolver rejects adding `setuptools>=83.0.0` while retaining the selected PyTorch build. This repository therefore records the finding instead of claiming a clean Python audit.

Review the exception when a compatible CPU PyTorch release becomes available, before a tagged release, and before any public deployment. Remove the CI ignore as soon as the dependency set can resolve with the patched setuptools version. Deployment owners should also review the advisory's current description and applicability to their build and runtime process.
