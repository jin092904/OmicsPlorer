# Frozen-evaluation row lineage runbook

This runbook prepares row-level metadata provenance for the manuscript's
frozen evaluation. It does not create a submission release or establish
metadata accuracy.

## Evidence boundary

Migration `0006_dataset_lineage` adds nullable `datasets.extraction_lineage_id`
and `datasets.build_stage` columns. It deliberately does not update existing
rows. Historical `extraction_version` labels do not prove the exact model
checkpoint, weight digest, prompt, parser options, or preceding processing
stages, so they must not be converted into verified lineage IDs by inference.

After migration, current non-model source paths record stable source lineage
IDs. Model-assisted writes remain fail-closed unless the operator supplies a
safe ID already defined in the frozen lineage manifest:

- `METADATA_EXTRACTION_LINEAGE_ID`: general metadata structuring;
- `ONTOLOGY_MAPPING_LINEAGE_ID`: frozen ontology normalization;
- `COHORT_EXTRACTION_LINEAGE_ID`: API on-demand cohort extraction;
- `PHASE3_EXTRACTION_LINEAGE_ID`: Phase 3 BioProject structuring;
- `SOL4_EXTRACTION_LINEAGE_ID`: Sol4 metadata enrichment.

An unset variable writes a null lineage. This is intentional and makes the row
ineligible for a frozen release. A model name or mutable Ollama tag is not a
lineage ID.

## Composite processing

Re-extraction, cohort extraction, and Sol4 can preserve fields from an earlier
row. When both the new stage and the existing parent are verified, the writer
stores a final ID in the form:

```text
<stage-lineage-id>.after.<parent-lineage-id>
```

The reproducibility manifest must declare that final lineage and its direct
parent using `parent_lineage_ids`. If either side is unknown, the final row
lineage remains null. Do not replace it with the stage ID alone.

## Deployment order

1. Freeze the exact model checkpoint/revision, weight digest, prompt, schema,
   options, serving engine, and deterministic post-processing revision.
2. Define safe lineage IDs and the acyclic parent graph in the reproducibility
   manifest. IDs may contain only letters, digits, `.`, `_`, and `-`.
3. Apply `uv run alembic upgrade head` from `apps/api`.
4. Supply only the lineage IDs corresponding to the frozen deployment and run
   the intended ingestion or reprocessing path.
5. Reindex the frozen corpus so PostgreSQL, Qdrant, and OpenSearch contain the
   same dataset membership and the two lineage fields.
6. Run the reproducibility repository's read-only evidence preflight. A null
   lineage, null build stage, empty corpus, duplicate accession, missing store,
   or unreadable index remains a blocker.

Rows left null must be reprocessed under a frozen lineage or excluded from the
frozen corpus with an explicit, prespecified rule. Do not issue an `UPDATE`
based only on historical version-name pattern matching.
