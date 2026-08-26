"""Unit + integration tests for GEO indexer.

Unit (no network/DB): _extract_from_payload — payload → field dict 매핑.
Integration (live NCBI + DB): GeoHarvester → index_geo_record 멱등성.
DB 가 없으면 integration 은 자동 skip.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.harvesters.geo import GeoHarvester
from src.indexer.geo import (
    EXTRACTION_VERSION,
    SOURCE_DB,
    _extract_from_payload,
    _has_processed_data_heuristic,
    _metadata_completeness,
    _parse_pdat,
    index_geo_record,
)

# asyncio_mode=auto 가 async 테스트만 자동 마킹 — pytestmark 불필요.


# ----- Unit ------------------------------------------------------------

def test_parse_pdat_valid() -> None:
    assert _parse_pdat("2026/04/21") == date(2026, 4, 21)


def test_parse_pdat_none_or_invalid() -> None:
    assert _parse_pdat(None) is None
    assert _parse_pdat("") is None
    assert _parse_pdat("not-a-date") is None


def test_has_processed_data_heuristic() -> None:
    assert _has_processed_data_heuristic({"suppfile": "GSE_RAW.tar"}) is True
    assert _has_processed_data_heuristic({"suppfile": ""}) is False
    assert _has_processed_data_heuristic({"suppfile": []}) is False
    assert _has_processed_data_heuristic({"suppfile": ["a", "b"]}) is True
    assert _has_processed_data_heuristic({}) is False


def test_metadata_completeness() -> None:
    full: dict[str, Any] = {
        "accession": "GSE1", "title": "T", "summary": "S",
        "taxon": "Homo sapiens", "gpl": "GPL1", "n_samples": 4, "pdat": "2026/01/01",
    }
    assert _metadata_completeness(full) == 1.0
    half = {k: v for k, v in list(full.items())[:4]}  # 4 of 7
    assert 0.5 < _metadata_completeness(half) < 0.6


def test_extract_from_payload_minimal() -> None:
    payload = {"result": {"100": {
        "accession": "GSE100", "title": "T", "summary": "S",
        "taxon": "Mus musculus", "n_samples": 4, "pdat": "2026/01/15",
        "gpl": "GPL21103", "suppfile": "GSE100_RAW.tar",
    }}}
    out = _extract_from_payload(payload, "100")
    assert out["source_db"] == SOURCE_DB
    assert out["source_id"] == "GSE100"
    assert out["title"] == "T"
    assert out["abstract"] == "S"
    assert out["n_samples"] == 4
    assert out["access_type"] == "open"
    assert out["has_processed_data"] is True
    assert out["submission_date"] == date(2026, 1, 15)
    assert out["last_update"] == date(2026, 1, 15)
    assert out["extraction_version"] == EXTRACTION_VERSION
    assert out["raw_metadata"] is payload  # 원본 보존 (참조 동일)


def test_extract_missing_uid_raises() -> None:
    with pytest.raises(ValueError, match="missing record"):
        _extract_from_payload({"result": {}}, "999")


def test_extract_missing_accession_raises() -> None:
    with pytest.raises(ValueError, match="no accession"):
        _extract_from_payload({"result": {"1": {"title": "x"}}}, "1")


def test_n_samples_string_to_int() -> None:
    payload = {"result": {"1": {
        "accession": "GSE1", "n_samples": "12", "pdat": "2026/01/01",
    }}}
    out = _extract_from_payload(payload, "1")
    assert out["n_samples"] == 12


# ----- Integration (live NCBI + DB) -----------------------------------

@pytest_asyncio.fixture
async def db_engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    eng = create_async_engine(url, poolclass=NullPool, future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.mark.integration
async def test_geo_pipeline_end_to_end_idempotent(db_engine) -> None:
    """실제 NCBI 에서 1건 fetch → index → 재 index 시 count 불변."""
    since = datetime.now(timezone.utc) - timedelta(days=14)
    async with GeoHarvester() as h:
        uid = None
        async for u in h.list_updated_since(since):
            uid = u
            break
        assert uid is not None, "NCBI 에서 최근 GSE 가 없음 (테스트 윈도우 늘려야 함)"
        payload = await h.fetch_raw(uid)

    accession = payload["result"][uid]["accession"]

    # 사전 정리 — 같은 accession 이 이미 있으면 삭제 (테스트 격리)
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("DELETE FROM datasets WHERE source_db='GEO' AND source_id=:a"),
                {"a": accession},
            )

    # 1차 INSERT
    async with db_engine.connect() as conn:
        async with conn.begin():
            r1 = await index_geo_record(conn, payload, uid)
        assert r1 == accession

    # 2차 — UPSERT, count 불변
    async with db_engine.connect() as conn:
        async with conn.begin():
            r2 = await index_geo_record(conn, payload, uid)
        assert r2 == accession

        result = await conn.execute(
            text("SELECT count(*) FROM datasets WHERE source_db='GEO' AND source_id=:a"),
            {"a": accession},
        )
        assert result.scalar() == 1

        result = await conn.execute(
            text("SELECT extraction_version, raw_metadata IS NOT NULL "
                 "FROM datasets WHERE source_db='GEO' AND source_id=:a"),
            {"a": accession},
        )
        ver, has_raw = result.fetchone()
        assert ver == EXTRACTION_VERSION
        assert has_raw

    # 사후 정리
    async with db_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("DELETE FROM datasets WHERE source_db='GEO' AND source_id=:a"),
                {"a": accession},
            )
