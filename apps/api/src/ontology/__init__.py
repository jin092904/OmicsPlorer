"""Ontology 매핑 — 마스터 플랜 §5.3.

OAK(`oaklib`) 기반 SQLite 어댑터가 v1+ 의 정식 경로지만, v0 는 OLS4 REST API 를
직접 호출하는 가벼운 어댑터로 부트스트랩. precision/throughput 기준 미달 시 oaklib 으로 교체.

Ontology 채택 (마스터 플랜 §5.3):
- MONDO  질병 (disease_ids)
- UBERON 해부학적 구조 / 조직 (tissue_ids)
- CL     세포 타입 (cell_type_ids)
- EFO    실험 / assay 메타 (assay_ids — v1+)
"""
