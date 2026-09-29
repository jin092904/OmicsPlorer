# Real-data GEO demo data (`geo-v1`)

This directory holds the data for `make docker-demo-geo`. With it, a reviewer or user can try
OmicsPlorer's full search path on a local computer: lexical search, vector search, rank fusion,
and cross-encoder reranking. The search runs over 5,000 real GEO Series.

| File | Content |
|---|---|
| `omicsplorer-demo-geo-v1.jsonl.gz` | One JSON record per GEO Series (5,000 records) |
| `omicsplorer-demo-geo-v1.manifest.json` | SHA-256 checksum, record counts, selection rule, and embedding-model build |

## What each record contains

- the public GEO Series accession (`source_id`);
- structured fields derived by OmicsPlorer: modality, organism taxonomy IDs, sample and subject
  counts, disease, tissue, and cell-type ontology IDs, access type, processed-data flag, platform,
  library strategy, submission date, and extraction version;
- the stored 1,024-dimensional document vector (float32, base64). It was computed from the title,
  summary, and library strategy/platform with `qwen3-embedding:8b`, using the Ollama build recorded
  in the manifest, and truncated to 1,024 dimensions;
- `abstract_pubmed_pmid`: when the full corpus appended a PubMed abstract to a short GEO summary,
  the PubMed ID that was used;
- `in_blinded_pool`: whether the Series was judged in the September 2026 blinded assessment.

The file contains no titles, summaries, abstracts, submitter names, contact details, raw submitter
metadata, or internal OmicsPlorer identifiers. At load time, `apps/workers/scripts/load_demo_geo.py`
fetches each title and summary from NCBI E-utilities (`esummary`, `db=gds`). Where the full corpus
used a PubMed abstract, the loader fetches that abstract from PubMed and appends it in the same
format. On 2026-09-27 the loader reproduced the full-corpus title and summary exactly for 4,990 of
the 4,998 Series that NCBI returned. The other eight differ because their submitters edited the text
on GEO after the full corpus was collected. Two Series in the file were not returned by NCBI and
are skipped.

## How the records were selected

The file first includes every GEO Series judged in the September 2026 blinded assessment that has a
stored vector (683 of 690). The remaining records are other GEO Series from the full corpus, in the
order of `md5("omicsplorer-demo-geo-v1" || accession)`, until the file has 5,000 records.
`apps/workers/scripts/export_demo_geo.py` performs this selection read-only against a full corpus.

Because the judged Series are included on purpose, the queries from that assessment return
meaningful results. The demo is therefore not a random sample of GEO. Its rankings are not
comparable with results on the full corpus, and it must not be used to measure retrieval quality.

## Search configuration used by the demo

The demo uses the retrieval settings of the deployed OmicsPlorer service:

- lexical (BM25) and vector candidates fused by reciprocal rank fusion (k = 60);
- the top 20 fused candidates reranked by `Qwen/Qwen3-Reranker-0.6B` at the Hugging Face revision
  pinned in `apps/api/src/services/reranker.py`.

Lexical search and reranking read the same text as in the full corpus. The lexical index is built
with the mapping in `apps/workers/src/indexer/lexical.py`, so source and facet filters also apply
to lexical candidates. Query translation, query understanding, and AI Pick are off. The demo is
designed for English queries.

Everything runs on CPU, and no GPU is needed. On the 4-vCPU runner used for CI, a search took
11–15 s once the models had loaded.

## Terms

GEO accessions are public identifiers. The titles, summaries, and PubMed abstracts that the loader
fetches remain subject to NCBI's policies and to any rights claimed by the original submitters or
publishers. They are fetched on each user's machine and are not redistributed in this repository.
The derived fields and vectors in this file are provided under the Creative Commons Attribution
4.0 International license (CC BY 4.0).
