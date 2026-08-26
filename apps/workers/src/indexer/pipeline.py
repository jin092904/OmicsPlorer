"""End-to-end pipeline: harvester → DB UPSERT → Qdrant embed → OpenSearch BM25.

스크립트로 ad-hoc 호출하거나 Celery task 가 wrap 한다.
멱등성: 모든 단계가 UPSERT — 같은 UID 를 두 번 실행해도 row 갯수 변화 없음.
"""
from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.extractors.llm_client import OllamaClient
from src.harvesters.base import Harvester
from src.indexer.embeddings import (
    ensure_collection,
    get_qdrant_client,
)
from src.indexer.embeddings import (
    refresh_payloads as qdrant_refresh_payloads,
)
from src.indexer.embeddings import (
    upsert_many as qdrant_upsert_many,
)
from src.indexer.geo import index_geo_record
from src.indexer.lexical import (
    ensure_index,
    get_os_client,
)
from src.indexer.lexical import (
    upsert_many as os_upsert_many,
)
from src.indexer.sra import index_sra_record

logger = logging.getLogger(__name__)


async def _index_single(
    conn, harvester: Harvester, uid: str
) -> str | None:
    """harvester→indexer 한 row. 실패 시 None 반환 (개별 실패가 batch 를 멈추지 않음)."""
    try:
        payload = await harvester.fetch_raw(uid)
    except Exception as e:
        logger.warning("fetch_raw failed src=%s uid=%s err=%s", harvester.source_db, uid, e)
        return None
    try:
        if harvester.source_db == "GEO":
            return await index_geo_record(conn, payload, uid)
        if harvester.source_db == "SRA":
            return await index_sra_record(conn, payload, uid)
        raise ValueError(f"unknown source_db {harvester.source_db!r}")
    except Exception as e:
        logger.warning("index failed src=%s uid=%s err=%s", harvester.source_db, uid, e)
        return None


async def harvest_and_index(
    eng: AsyncEngine,
    harvester: Harvester,
    uids: list[str],
) -> dict[str, int]:
    """DB UPSERT 단계만 실행 — embed/BM25 는 별도 step.

    반환: {'attempted': N, 'inserted': M}.
    """
    inserted = 0
    async with eng.connect() as conn:
        async with conn.begin():
            for uid in uids:
                acc = await _index_single(conn, harvester, uid)
                if acc:
                    inserted += 1
    return {"attempted": len(uids), "inserted": inserted}


async def reindex_all_search_layers(eng: AsyncEngine) -> dict[str, int]:
    """DB 전체를 Qdrant + OpenSearch 에 다시 색인. 매번 UPSERT 라 안전."""
    qdrant = get_qdrant_client()
    os_client = get_os_client()
    try:
        await ensure_collection(qdrant)
        await ensure_index(os_client)

        async with eng.connect() as conn:
            result = await conn.execute(text("""
                SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
                       disease_ids, tissue_ids, cell_type_ids,
                       access_type, has_processed_data, submission_date,
                       n_samples, n_subjects, platform, library_strategy, extraction_version
                  FROM datasets ORDER BY submission_date DESC NULLS LAST
            """))
            rows = [dict(r._mapping) for r in result.fetchall()]

        async with OllamaClient() as ollama:
            qdrant_count = await qdrant_upsert_many(qdrant, ollama, rows)
        os_count = await os_upsert_many(os_client, rows)
        return {"datasets_in_db": len(rows), "qdrant_upserts": qdrant_count, "opensearch_upserts": os_count}
    finally:
        await qdrant.close()
        await os_client.close()


async def refresh_qdrant_payloads_only(eng: AsyncEngine) -> dict[str, int]:
    """Qdrant 점들의 payload 만 DB 의 최신 행으로 덮어쓴다 (벡터 미변경).

    `_payload()` 가 추가 표시 필드(title 등)를 포함하도록 변경된 뒤 1회 실행.
    재임베딩이 없으므로 ~10K 행도 1분 안에 마무리된다.
    """
    qdrant = get_qdrant_client()
    try:
        await ensure_collection(qdrant)
        async with eng.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT id, source_db, source_id, title, abstract,
                           modality, organism_taxid,
                           disease_ids, tissue_ids, cell_type_ids,
                           access_type, has_processed_data, submission_date,
                           n_samples, n_subjects, platform, library_strategy
                      FROM datasets
                    """
                )
            )
            rows = [dict(r._mapping) for r in result.fetchall()]
        updated = await qdrant_refresh_payloads(qdrant, rows)
        return {"datasets_in_db": len(rows), "qdrant_payloads_updated": updated}
    finally:
        await qdrant.close()


async def collect_uids(harvester: Harvester, since, max_uids: int) -> list[str]:
    out: list[str] = []
    async for uid in harvester.list_updated_since(since):
        out.append(uid)
        if len(out) >= max_uids:
            break
    return out
