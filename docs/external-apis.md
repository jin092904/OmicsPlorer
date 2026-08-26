# External metadata services

This file identifies network services referenced by the published source. It deliberately does not copy volatile quotas, record counts, prices, or availability promises. Check each provider's current official documentation and terms before a collection run.

| Source | Code location | Configured base endpoint | Intended data |
|---|---|---|---|
| NCBI GEO / E-utilities | `apps/workers/src/harvesters/geo.py` | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` | Public GEO study metadata |
| NCBI SRA / E-utilities | `apps/workers/src/harvesters/sra.py` | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/` | Public SRA study metadata |
| NCBI GEO FTP | `apps/workers/src/harvesters/geo_matrix.py` | `https://ftp.ncbi.nlm.nih.gov/geo/series/` | Public series-matrix metadata |
| NCI Genomic Data Commons | `apps/workers/src/harvesters/gdc.py` | `https://api.gdc.cancer.gov/` | Open-access project metadata |
| Human Cell Atlas Azul | `apps/workers/src/harvesters/hca.py` | `https://service.azul.data.humancellatlas.org/` | Public HCA metadata exposed by Azul |
| EMBL-EBI OLS4 | `apps/workers/src/ontology/mapper.py` | `https://www.ebi.ac.uk/ols4/api` | Ontology term lookup |

Some maintenance scripts also call NCBI E-utilities, the ENA browser, or OLS4. Search the exact release with `rg 'https?://' apps/workers` when preparing a network-access inventory.

## Release checklist

For every enabled source, record alongside the run:

1. source name, official documentation and terms URL;
2. endpoint and access date;
3. authentication and requester-identification method, without recording secrets;
4. configured request rate, retry/backoff, timeout, and pagination behavior;
5. requested record scope and controlled-access exclusions;
6. response schema or API version when one is supplied;
7. raw-response retention and redistribution decision;
8. failures, partial pages, and the resume/watermark state.

An endpoint appearing in source code does not establish permission to redistribute every returned field. API terms and dataset-level access conditions remain authoritative. Use a managed contact address in request headers or parameters where a provider requests identification; do not hard-code a personal email address.

## Reproducibility boundary

This document describes the application integration points. A manuscript run requires a frozen acquisition manifest in the reproducibility repository, including exact dates, source commit, configuration hashes, successful and failed request counts, and the resulting corpus manifest. Current live API output is not a substitute for that frozen record.
