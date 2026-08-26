"""OLS4 mapper.py 회귀 테스트.

Live OLS4 호출 — 네트워크 reachable 한지 socket probe 후 skip.
"""
from __future__ import annotations

import socket

import pytest

from src.ontology.mapper import OntologyMapper, lookup_many


def _ols4_reachable() -> bool:
    try:
        with socket.create_connection(("www.ebi.ac.uk", 443), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _ols4_reachable(), reason="OLS4 not reachable")


@pytest.mark.asyncio
async def test_lookup_disease_canonical() -> None:
    async with OntologyMapper() as m:
        match = await m.lookup("lung adenocarcinoma", "mondo")
    assert match is not None
    assert match.curie == "MONDO:0005061"
    assert match.label == "lung adenocarcinoma"


@pytest.mark.asyncio
async def test_lookup_tissue_common_term() -> None:
    """canonical tissue 인 'lung' 이 정확하게 매칭되는지 — /search?exact=true 가 핵심."""
    async with OntologyMapper() as m:
        match = await m.lookup("lung", "uberon")
    assert match is not None
    assert match.curie == "UBERON:0002048"


@pytest.mark.asyncio
async def test_lookup_synonym_match() -> None:
    """exact_synonym 매칭 — 'PBMC' 같은 약어/별칭은 label 이 아니지만 synonym 으로 매칭."""
    async with OntologyMapper() as m:
        match = await m.lookup("peripheral blood mononuclear cell", "cl")
    assert match is not None
    assert match.curie == "CL:2000001"


@pytest.mark.asyncio
async def test_lookup_unknown_returns_none() -> None:
    """매칭 실패는 None — 학술 사용자 noise tolerance 가 낮으므로 fuzzy 매칭 거부."""
    async with OntologyMapper() as m:
        match = await m.lookup("zxqv-totally-not-a-disease-1234", "mondo")
    assert match is None


@pytest.mark.asyncio
async def test_lookup_caches_result() -> None:
    """동일 (text, ontology) 두 번째 호출은 cache hit — 외부 호출 없음."""
    async with OntologyMapper() as m:
        m1 = await m.lookup("lung adenocarcinoma", "mondo")
        m2 = await m.lookup("LUNG ADENOCARCINOMA", "mondo")  # case-insensitive cache key
    assert m1 == m2


@pytest.mark.asyncio
async def test_lookup_many_dedups() -> None:
    """같은 curie 가 여러 input string 에서 매칭되어도 결과는 dedup."""
    async with OntologyMapper() as m:
        out = await lookup_many(m, ["lung adenocarcinoma", "adenocarcinoma of lung"], "mondo")
    # 두 input 다 같은 MONDO:0005061 으로 매칭되어야 함
    assert len(out) == 1
    assert out[0].curie == "MONDO:0005061"


@pytest.mark.asyncio
async def test_empty_input_returns_none() -> None:
    async with OntologyMapper() as m:
        assert await m.lookup("", "mondo") is None
        assert await m.lookup("   ", "mondo") is None
