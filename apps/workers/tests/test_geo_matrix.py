"""Series Matrix 파서 unit 테스트.

network 없이 inline 텍스트로 검증. 정규화 (sex/age) 도 함께.
"""
from __future__ import annotations

import pytest

from src.harvesters.geo_matrix import (
    GeoMatrixHarvester,
    _normalize_age,
    _normalize_sex,
    parse_series_matrix,
)

# ----- _normalize_sex --------------------------------------------------

def test_normalize_sex_canonical() -> None:
    assert _normalize_sex("male") == "male"
    assert _normalize_sex("Female") == "female"
    assert _normalize_sex("M") == "male"
    assert _normalize_sex("f") == "female"


def test_normalize_sex_korean() -> None:
    assert _normalize_sex("남") == "male"
    assert _normalize_sex("여성") == "female"


def test_normalize_sex_unknown() -> None:
    assert _normalize_sex("intersex") is None
    assert _normalize_sex(None) is None
    assert _normalize_sex("") is None


# ----- _normalize_age --------------------------------------------------

def test_normalize_age_years() -> None:
    assert _normalize_age("45 years") == (45.0, "year")
    assert _normalize_age("23") == (23.0, "year")
    assert _normalize_age("80 yr") == (80.0, "year")


def test_normalize_age_months_days() -> None:
    assert _normalize_age("6 months") == (6.0, "month")
    assert _normalize_age("14 days") == (14.0, "day")
    assert _normalize_age("3 weeks") == (21.0, "day")  # week → day ×7


def test_normalize_age_range() -> None:
    val, unit = _normalize_age("18-25")
    assert val == 21.5
    assert unit == "year"


def test_normalize_age_unknown() -> None:
    assert _normalize_age("unknown") == (None, None)
    assert _normalize_age("N/A") == (None, None)
    assert _normalize_age("") == (None, None)
    assert _normalize_age(None) == (None, None)


# ----- parse_series_matrix ---------------------------------------------

SAMPLE_MATRIX = '\n'.join([
    '!Series_title\t"Liver cancer cohort"',
    '!Sample_geo_accession\t"GSM1"\t"GSM2"\t"GSM3"\t"GSM4"',
    '!Sample_title\t"P1"\t"P2"\t"P3"\t"P4"',
    '!Sample_characteristics_ch1\t"sex: male"\t"sex: female"\t"sex: male"\t"sex: female"',
    '!Sample_characteristics_ch1\t"age: 45"\t"age: 52"\t"age: 38"\t"age: 60"',
    '!Sample_characteristics_ch1\t"disease state: tumor"\t"disease state: tumor"\t"disease state: normal"\t"disease state: normal"',
    '!Sample_characteristics_ch1\t"treatment: anti-PD1"\t"treatment: none"\t"treatment: none"\t"treatment: none"',
])


def test_parse_series_matrix_basic() -> None:
    rows = parse_series_matrix(SAMPLE_MATRIX)
    assert len(rows) == 4
    assert [r["source_sample_id"] for r in rows] == ["GSM1", "GSM2", "GSM3", "GSM4"]
    assert [r["sex"] for r in rows] == ["male", "female", "male", "female"]
    assert [r["age_value"] for r in rows] == [45.0, 52.0, 38.0, 60.0]
    assert all(r["age_unit"] == "year" for r in rows)
    assert [r["disease_state"] for r in rows] == ["tumor", "tumor", "normal", "normal"]
    assert rows[0]["treatment"] == "anti-PD1"
    # raw_attributes 보존
    assert "sex" in rows[0]["raw_attributes"]
    assert rows[0]["raw_attributes"]["disease state"] == "tumor"


def test_parse_series_matrix_no_samples_line() -> None:
    text = '!Series_title\t"x"\n!Series_summary\t"y"\n'
    rows = parse_series_matrix(text)
    assert rows == []


def test_parse_series_matrix_handles_quoted_and_missing() -> None:
    text = '\n'.join([
        '!Sample_geo_accession\t"GSM1"\t"GSM2"',
        '!Sample_characteristics_ch1\t"sex: male"\t""',  # 두번째 sample 비어있음
    ])
    rows = parse_series_matrix(text)
    assert len(rows) == 2
    assert rows[0]["sex"] == "male"
    assert rows[1]["sex"] is None  # 빈 string 은 매칭 안 됨


# ----- _matrix_url -----------------------------------------------------

def test_matrix_url_stub() -> None:
    h = GeoMatrixHarvester()
    try:
        assert h._matrix_url("GSE176178").endswith(
            "GSE176nnn/GSE176178/matrix/GSE176178_series_matrix.txt.gz"
        )
        assert h._matrix_url("GSE9").endswith(
            "GSEnnn/GSE9/matrix/GSE9_series_matrix.txt.gz"
        )
        assert h._matrix_url("GSE1000").endswith(
            "GSE1nnn/GSE1000/matrix/GSE1000_series_matrix.txt.gz"
        )
    finally:
        import asyncio
        asyncio.run(h.aclose())


def test_matrix_url_rejects_invalid() -> None:
    h = GeoMatrixHarvester()
    try:
        with pytest.raises(ValueError):
            h._matrix_url("PRJNA123")
    finally:
        import asyncio
        asyncio.run(h.aclose())
