"""Snippet 생성기 unit 테스트 — pure function 이라 DB 없이 검증.

source 별 1개 이상의 snippet 이 나와야 함, accession 이 코드 내부에 정확히 박혔는지,
unknown source 는 빈 리스트.
"""
from __future__ import annotations

from src.services.snippets import (
    SUPPORTED_LANGUAGES,
    build_snippets,
)

# ----- 기본 동작 -------------------------------------------------------

def test_geo_snippets_include_accession() -> None:
    out = build_snippets("GEO", "GSE176178")
    assert len(out) >= 3
    for s in out:
        assert "GSE176178" in s["code"]
        assert s["language"] in SUPPORTED_LANGUAGES


def test_sra_snippets_include_accession() -> None:
    out = build_snippets("SRA", "SRP123456")
    assert len(out) >= 1
    assert any("SRP123456" in s["code"] for s in out)


def test_hca_snippets_include_id() -> None:
    out = build_snippets("HCA", "abc-123")
    assert len(out) >= 1
    assert any("abc-123" in s["code"] for s in out)


def test_gdc_snippets_include_id() -> None:
    out = build_snippets("GDC", "TCGA-LUAD")
    assert len(out) >= 1
    assert any("TCGA-LUAD" in s["code"] for s in out)


def test_unknown_source_empty_and_ena_is_supported() -> None:
    assert build_snippets("FOO", "X1") == []
    out = build_snippets("ENA", "PRJEB1")
    assert len(out) >= 1
    assert any("PRJEB1" in s["code"] for s in out)


def test_empty_source_id_empty() -> None:
    assert build_snippets("GEO", "") == []
    assert build_snippets("GEO", "   ") == []


def test_source_db_case_insensitive() -> None:
    assert len(build_snippets("geo", "GSE1")) > 0
    assert len(build_snippets("Geo", "GSE1")) > 0


# ----- snippet 구조 검증 -----------------------------------------------

def test_snippet_fields_present() -> None:
    out = build_snippets("GEO", "GSE1")
    for s in out:
        assert isinstance(s["title"], str) and s["title"]
        assert isinstance(s["description"], str) and s["description"]
        assert isinstance(s["code"], str) and s["code"]
        assert isinstance(s["requires"], list)
        assert s["language"] in SUPPORTED_LANGUAGES


def test_geo_supplementary_uses_correct_ftp_stub() -> None:
    """GSE176178 → GSE176nnn stub 가 bash 스니펫에 정확히 들어가는지."""
    out = build_snippets("GEO", "GSE176178")
    bash = next(s for s in out if s["language"] == "bash")
    # ${GSE%???}nnn 표현이 있는지 (stub 변수 치환은 런타임에 일어남)
    assert "GSE%???" in bash["code"] or "GSE176nnn" in bash["code"]
