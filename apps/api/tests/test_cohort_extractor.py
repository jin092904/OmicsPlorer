"""api 측 cohort_extractor unit tests — workers/extractors/cohort_design 과 동일 prompt/schema 검증.

LLM 호출 자체는 mock — Ollama 미가용 환경에서도 통과.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from src.services import cohort_extractor as ce

# ----- prompt / schema 정합성 (workers 측과 동기) ---------------------

def test_prompt_includes_user_input_block() -> None:
    p = ce.build_prompt("T", "A", [{"label": "x", "count": 3}])
    assert "<user_input>" in p
    assert "</user_input>" in p
    assert "TITLE: T" in p
    assert "x: n=3" in p


def test_prompt_truncates_abstract() -> None:
    # Phi-4 mini JSON schema stuck 회피 위해 1200 자로 truncate.
    p = ce.build_prompt(None, "Z" * 4000)
    assert "Z" * 1200 in p
    assert "Z" * 1500 not in p


def test_allowed_roles_match_workers() -> None:
    # 두 모듈 (api / workers) 의 ALLOWED_ROLES 가 동일해야 cohort_design_version 호환.
    # workers 모듈을 직접 import 하지 않으므로 hardcoded 비교 — 한쪽이 바뀌면 양쪽 동시 갱신.
    assert ce.ALLOWED_ROLES == {"case", "control", "treatment", "comparison", "other"}


def test_allowed_design_types_match_workers() -> None:
    assert ce.ALLOWED_DESIGN_TYPES == {
        "case_control", "cohort", "cross_sectional", "rct",
        "time_series", "unknown",
    }


def test_version_pinned() -> None:
    assert ce.COHORT_DESIGN_VERSION.startswith("cohort-v2-")


def test_prompt_includes_sample_factors_varying() -> None:
    factors = {
        "varying": [
            {"factor": "age", "values": [
                {"value": "12-weeks", "count": 7},
                {"value": "68-weeks", "count": 7},
            ]},
        ],
        "constant": [],
    }
    p = ce.build_prompt("t", "a", None, factors)
    assert "SAMPLE FACTORS" in p
    assert "Group variables" in p
    assert "age" in p
    assert "12-weeks (n=7)" in p
    assert "68-weeks (n=7)" in p


def test_prompt_includes_sample_factors_constant() -> None:
    factors = {
        "varying": [],
        "constant": [
            {"factor": "sex", "value": "Male", "count": 14},
            {"factor": "tissue", "value": "Heart", "count": 14},
        ],
    }
    p = ce.build_prompt("t", "a", None, factors)
    assert "Constant variables" in p
    assert "sex: Male (n=14)" in p
    assert "tissue: Heart (n=14)" in p


def test_prompt_omits_factors_when_empty() -> None:
    p = ce.build_prompt("t", "a", None, {"varying": [], "constant": []})
    # SAMPLE FACTORS 헤더 단어는 system prompt 에도 있으므로 <user_input> 안에 없는지 확인
    user_block = p.split("<user_input>")[1].split("</user_input>")[0]
    assert "SAMPLE FACTORS" not in user_block


def test_format_sample_factors_caps_lists() -> None:
    factors = {
        "varying": [
            {"factor": f"f{i}", "values": [{"value": "x", "count": 1}, {"value": "y", "count": 1}]}
            for i in range(10)
        ],
        "constant": [
            {"factor": f"c{i}", "value": "v", "count": 1} for i in range(20)
        ],
    }
    out = ce._format_sample_factors(factors)
    # varying 최대 6, constant 최대 8
    assert out.count("    - f") == 6
    assert out.count("    - c") == 8


# ----- validate_design --------------------------------------------------

def test_validate_drops_invalid_groups() -> None:
    parsed = {
        "groups": [
            {"label": "", "role": "case", "criteria": "x"},
            {"label": "OK", "role": "weird-role", "criteria": "x"},
        ],
        "design_type": "cohort",
    }
    out = ce.validate_design(parsed)
    assert len(out["groups"]) == 1
    assert out["groups"][0]["role"] == "other"  # weird-role → other


def test_validate_unknown_design_type_fallback() -> None:
    out = ce.validate_design({
        "groups": [{"label": "g", "role": "case", "criteria": "x"}],
        "design_type": "scifi",
    })
    assert out["design_type"] == "unknown"


def test_validate_non_object_raises() -> None:
    with pytest.raises(ValueError):
        ce.validate_design("nope")  # type: ignore[arg-type]


# ----- extract_cohort_design_ondemand: mock httpx ---------------------

class _FakeResp:
    def __init__(self, json_body: dict) -> None:
        self._body = json_body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class _FakeClient:
    def __init__(self, json_body: dict) -> None:
        self._body = json_body

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, json: dict) -> _FakeResp:
        return _FakeResp(self._body)


@pytest.mark.asyncio
async def test_ondemand_returns_validated_design(monkeypatch) -> None:
    fake_resp_body = {
        "response": json.dumps({
            "groups": [
                {"label": "Disease", "role": "case", "n": 87, "criteria": "stage III IBD"},
                {"label": "Healthy", "role": "control", "n": 42, "criteria": "age-matched"},
            ],
            "design_type": "case_control",
            "notes": "clear comparison",
        }),
    }
    monkeypatch.setattr(
        ce.httpx, "AsyncClient",
        lambda *a, **kw: _FakeClient(fake_resp_body),
    )
    out = await ce.extract_cohort_design_ondemand("t", "a")
    assert out is not None
    assert out["design_type"] == "case_control"
    assert len(out["groups"]) == 2


@pytest.mark.asyncio
async def test_ondemand_returns_none_on_empty_groups(monkeypatch) -> None:
    fake_resp_body = {
        "response": json.dumps({"groups": [], "design_type": "unknown"}),
    }
    monkeypatch.setattr(
        ce.httpx, "AsyncClient",
        lambda *a, **kw: _FakeClient(fake_resp_body),
    )
    out = await ce.extract_cohort_design_ondemand("t", "a")
    assert out is None


@pytest.mark.asyncio
async def test_ondemand_returns_none_on_invalid_json(monkeypatch) -> None:
    fake_resp_body = {"response": "not json at all"}
    monkeypatch.setattr(
        ce.httpx, "AsyncClient",
        lambda *a, **kw: _FakeClient(fake_resp_body),
    )
    out = await ce.extract_cohort_design_ondemand("t", "a")
    assert out is None


@pytest.mark.asyncio
async def test_ondemand_returns_none_on_no_input() -> None:
    assert await ce.extract_cohort_design_ondemand(None, None) is None
    assert await ce.extract_cohort_design_ondemand("", "") is None
