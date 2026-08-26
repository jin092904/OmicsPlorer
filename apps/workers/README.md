# OmicsPlorer — Workers

Celery 기반 비동기 작업: harvester (source DB 수집) → extractor (LLM 구조화) → ontology mapper → indexer (Qdrant + OpenSearch). 자세한 설계는 모노레포 루트의 [`docs/`](../../docs/) 참조.
