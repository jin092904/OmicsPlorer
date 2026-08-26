"""Embedding pipeline — datasets row → 1024-dim 임베딩 → Qdrant collection.

마스터 플랜 §6:
    Hybrid retrieval = BM25 (OpenSearch) + Dense (Qdrant)
    Qdrant payload 에 dataset_id, modality, organism_taxid, access_type, n_subjects, submission_date 복제

ADR 0003: 사용자 쿼리 임베딩은 Qdrant 에 절대 저장하지 않는다 (T7) — 본 모듈은 dataset(L0)
임베딩만 다루므로 그 제약과 무관.

Collection 이름: 'datasets_v2' (ADR 0006 의 모델 stack 변경으로 fork).
v1 (768d, nomic-embed-text) → v2 (1024d, Qwen3-Embedding 시리즈).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from src.extractors.llm_client import OllamaClient

logger = logging.getLogger(__name__)

# ADR 0006: Qwen3-Embedding 시리즈로 교체. v2 fork.
# - Indexing 시점 (A100): Qwen3-Embedding-8B native 4096d → Matryoshka 1024d truncate
# - Query 시점 (serve): Qwen3-Embedding-0.6B native 1024d
# - 두 모델의 1024d 가 호환 (Matryoshka 디자인 + 0.6B native dim 일치)
COLLECTION_NAME = "datasets_v2"
EMBED_DIM = 1024  # Qwen3-Embedding 시리즈 (8B Matryoshka 1024d / 0.6B native 1024d)
DEFAULT_QDRANT_URL = "http://localhost:6333"


def get_qdrant_client() -> AsyncQdrantClient:
    url = os.environ.get("QDRANT_URL", DEFAULT_QDRANT_URL)
    return AsyncQdrantClient(url=url)


async def ensure_collection(qdrant: AsyncQdrantClient) -> None:
    """idempotent — 컬렉션이 없으면 생성. 있으면 dim/distance 가 일치하는지만 확인."""
    collections = await qdrant.get_collections()
    names = [c.name for c in collections.collections]
    if COLLECTION_NAME in names:
        info = await qdrant.get_collection(COLLECTION_NAME)
        existing_dim = info.config.params.vectors.size
        existing_dist = info.config.params.vectors.distance
        if existing_dim != EMBED_DIM or existing_dist != Distance.COSINE:
            raise RuntimeError(
                f"Qdrant collection {COLLECTION_NAME!r} has mismatched config: "
                f"dim={existing_dim} dist={existing_dist} expected dim={EMBED_DIM} dist={Distance.COSINE}"
            )
        return
    await qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
    )
    logger.info("created qdrant collection %s dim=%d", COLLECTION_NAME, EMBED_DIM)


def _compose_text(dataset_row: dict[str, Any]) -> str:
    """임베딩 입력 텍스트 — title + abstract + library_strategy/platform 약간."""
    parts = []
    if dataset_row.get("title"):
        parts.append(dataset_row["title"])
    if dataset_row.get("abstract"):
        parts.append(dataset_row["abstract"])
    extras = []
    if dataset_row.get("library_strategy"):
        extras.append(f"library_strategy: {dataset_row['library_strategy']}")
    if dataset_row.get("platform"):
        extras.append(f"platform: {dataset_row['platform']}")
    if extras:
        parts.append(" | ".join(extras))
    return "\n\n".join(parts) if parts else ""


# OpenSearch BM25 가 0건 매칭하는 경우 (예: 한국어 쿼리 → 영어 코퍼스) 결과 카드는 Qdrant
# payload 만으로 렌더된다. 표시·랭킹에 필요한 필드는 모두 payload 에 포함시킨다.
_ABSTRACT_SNIPPET_LIMIT = 600  # rerank/표시 양쪽에 쓰기엔 충분, 페이로드 크기 부담은 작음.


def _payload(dataset_row: dict[str, Any]) -> dict[str, Any]:
    """Qdrant payload — 필터 + 카드 표시 + cross-encoder rerank 입력용."""
    abstract = dataset_row.get("abstract") or ""
    return {
        "dataset_id": str(dataset_row["id"]),
        "source_db": dataset_row["source_db"],
        "source_id": dataset_row["source_id"],
        "title": dataset_row.get("title"),
        "abstract": abstract[:_ABSTRACT_SNIPPET_LIMIT] if abstract else None,
        "modality": dataset_row.get("modality") or [],
        "organism_taxid": dataset_row.get("organism_taxid") or [],
        "disease_ids": dataset_row.get("disease_ids") or [],
        "tissue_ids": dataset_row.get("tissue_ids") or [],
        "cell_type_ids": dataset_row.get("cell_type_ids") or [],
        "library_strategy": dataset_row.get("library_strategy"),
        "platform": dataset_row.get("platform"),
        "access_type": dataset_row["access_type"],
        "has_processed_data": bool(dataset_row.get("has_processed_data", False)),
        "submission_date": (
            dataset_row["submission_date"].isoformat()
            if dataset_row.get("submission_date") else None
        ),
        "n_samples": dataset_row.get("n_samples"),
        "n_subjects": dataset_row.get("n_subjects"),
    }


async def upsert_embedding(
    qdrant: AsyncQdrantClient,
    ollama: OllamaClient,
    dataset_row: dict[str, Any],
) -> str:
    """단일 dataset row 를 임베딩하고 Qdrant 에 upsert.

    반환값: dataset_id (string).
    point_id 는 dataset_id (UUID) — Qdrant 는 UUID string 을 그대로 받는다.
    """
    text = _compose_text(dataset_row)
    if not text:
        raise ValueError(f"empty text for dataset_id={dataset_row['id']}")
    vectors = await ollama.embed(text, truncate_dim=EMBED_DIM)
    vec = vectors[0]
    if len(vec) != EMBED_DIM:
        raise ValueError(
            f"embedding dim mismatch: got {len(vec)} expected {EMBED_DIM} "
            "(check OLLAMA_MODEL_EMBED — model 변경 시 collection 재생성 필요)"
        )
    pid = str(dataset_row["id"])
    await qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[PointStruct(id=pid, vector=vec, payload=_payload(dataset_row))],
    )
    return pid


async def refresh_payloads(
    qdrant: AsyncQdrantClient,
    dataset_rows: list[dict[str, Any]],
    batch_size: int = 256,
) -> int:
    """기존 point 의 payload 만 갱신 (벡터 미변경, 임베딩 재생성 없음).

    `_payload()` 가 추가된 표시 필드를 포함하도록 변경된 뒤, 기존 색인을 빠르게
    동기화하기 위한 유틸. set_payload 는 기존 키를 부분 갱신 (다른 키는 보존) 하므로
    오래된 키가 남아있다면 정확한 미러링을 위해 overwrite_payload 를 쓴다.
    """
    updated = 0
    for i in range(0, len(dataset_rows), batch_size):
        batch = dataset_rows[i : i + batch_size]
        for row in batch:
            pid = str(row["id"])
            await qdrant.overwrite_payload(
                collection_name=COLLECTION_NAME,
                payload=_payload(row),
                points=[pid],
            )
            updated += 1
    return updated


async def upsert_many(
    qdrant: AsyncQdrantClient,
    ollama: OllamaClient,
    dataset_rows: list[dict[str, Any]],
    batch_size: int = 32,
) -> int:
    """여러 dataset row 를 batch 로 임베딩하고 Qdrant 에 upsert."""
    upserted = 0
    for i in range(0, len(dataset_rows), batch_size):
        batch = dataset_rows[i : i + batch_size]
        texts = [_compose_text(r) for r in batch]
        # 빈 텍스트 row 는 건너뛴다
        active_indexes = [j for j, t in enumerate(texts) if t]
        if not active_indexes:
            continue
        vectors = await ollama.embed([texts[j] for j in active_indexes], truncate_dim=EMBED_DIM)
        if len(vectors) != len(active_indexes):
            raise RuntimeError(f"embed batch returned {len(vectors)} vectors, expected {len(active_indexes)}")
        # 방어: batch 의 첫 벡터만 dim 검증 (truncate_dim 이 적용됐다면 항상 EMBED_DIM)
        if vectors and len(vectors[0]) != EMBED_DIM:
            raise ValueError(
                f"embed batch dim mismatch: got {len(vectors[0])} expected {EMBED_DIM} "
                "(check OLLAMA_MODEL_EMBED — model 변경 시 collection 재생성 필요)"
            )
        points = []
        for j, vec in zip(active_indexes, vectors):
            row = batch[j]
            pid = str(row["id"])
            points.append(PointStruct(id=pid, vector=vec, payload=_payload(row)))
        await qdrant.upsert(collection_name=COLLECTION_NAME, points=points)
        upserted += len(points)
    return upserted
