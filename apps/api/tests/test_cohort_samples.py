"""cohort_samples 의 _summarize_age — pure function 검증 (DB 없이)."""
from __future__ import annotations

from src.services.cohort_samples import _summarize_age


def test_summarize_age_empty() -> None:
    out = _summarize_age([])
    assert out == {"unit": None, "min": None, "max": None, "median": None, "buckets": []}


def test_summarize_age_single_unit() -> None:
    rows = [{"age_unit": "year", "age_value": v} for v in [20, 25, 30, 35, 40]]
    out = _summarize_age(rows)
    assert out["unit"] == "year"
    assert out["min"] == 20
    assert out["max"] == 40
    assert out["median"] == 30
    # 5종 bucket — 총 합은 5
    total = sum(b["count"] for b in out["buckets"])
    assert total == 5


def test_summarize_age_picks_dominant_unit() -> None:
    rows = (
        [{"age_unit": "year", "age_value": v} for v in [20, 30, 40]]
        + [{"age_unit": "month", "age_value": 6}]
    )
    out = _summarize_age(rows)
    assert out["unit"] == "year"
    # month entry 는 무시
    assert out["min"] == 20
    assert out["max"] == 40


def test_summarize_age_zero_span() -> None:
    rows = [{"age_unit": "year", "age_value": 50} for _ in range(3)]
    out = _summarize_age(rows)
    assert out["min"] == 50
    assert out["max"] == 50
    assert len(out["buckets"]) == 1
    assert out["buckets"][0]["count"] == 3


def test_summarize_age_median_even() -> None:
    rows = [{"age_unit": "year", "age_value": v} for v in [10, 20, 30, 40]]
    out = _summarize_age(rows)
    assert out["median"] == 25  # (20+30)/2
