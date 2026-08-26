"""cohort_design extractor unit tests — LLM 호출 없이 prompt 빌드 + 응답 검증."""
from __future__ import annotations

import json

import pytest

from src.extractors import cohort_design as cd

# ----- build_prompt ----------------------------------------------------

def test_build_prompt_truncates_long_abstract() -> None:
    long_abs = "A" * 5000
    prompt = cd.build_prompt("title", long_abs)
    # 2000자 cap + 'ABSTRACT: ' 접두
    assert "A" * 2000 in prompt
    assert "A" * 2500 not in prompt


def test_build_prompt_includes_condition_dist() -> None:
    dist = [{"label": "tumor", "count": 30}, {"label": "normal", "count": 15}]
    prompt = cd.build_prompt("t", "a", dist)
    assert "tumor: n=30" in prompt
    assert "normal: n=15" in prompt


def test_build_prompt_omits_empty_parts() -> None:
    prompt = cd.build_prompt(None, "abstract only")
    assert "TITLE" not in prompt
    assert "abstract only" in prompt


def test_build_prompt_wraps_user_input() -> None:
    prompt = cd.build_prompt("t", "a")
    assert "<user_input>" in prompt
    assert "</user_input>" in prompt


def test_build_prompt_includes_sample_factors() -> None:
    factors = {
        "varying": [
            {"factor": "genotype", "values": [
                {"value": "WT", "count": 5},
                {"value": "KO", "count": 5},
            ]},
        ],
        "constant": [{"factor": "tissue", "value": "Liver", "count": 10}],
    }
    p = cd.build_prompt("t", "a", None, factors)
    assert "SAMPLE FACTORS" in p
    assert "genotype: WT (n=5), KO (n=5)" in p
    assert "tissue: Liver (n=10)" in p


def test_build_prompt_skips_empty_factors() -> None:
    p = cd.build_prompt("t", "a", None, {"varying": [], "constant": []})
    # SAMPLE FACTORS 단어는 system prompt 에도 있어서 user_input 블록 안만 확인
    user_block = p.split("<user_input>")[1].split("</user_input>")[0]
    assert "SAMPLE FACTORS" not in user_block


def test_version_v2() -> None:
    assert cd.COHORT_DESIGN_VERSION.startswith("cohort-v2-")


# ----- _parse_response -------------------------------------------------

def test_parse_response_plain_json() -> None:
    raw = '{"groups": [], "design_type": "unknown"}'
    assert cd._parse_response(raw) == {"groups": [], "design_type": "unknown"}


def test_parse_response_strips_code_fence() -> None:
    raw = "```json\n{\"groups\": [], \"design_type\": \"unknown\"}\n```"
    assert cd._parse_response(raw)["design_type"] == "unknown"


def test_parse_response_invalid_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        cd._parse_response("not json")


# ----- _validate -------------------------------------------------------

def test_validate_happy_path() -> None:
    parsed = {
        "groups": [
            {"label": "Disease", "role": "case", "n": 87, "criteria": "stage III"},
            {"label": "Healthy", "role": "control", "n": 42, "criteria": "age-matched"},
        ],
        "design_type": "case_control",
        "notes": "clear comparison",
    }
    out = cd._validate(parsed)
    assert out["design_type"] == "case_control"
    assert len(out["groups"]) == 2
    assert out["groups"][0]["role"] == "case"
    assert out["groups"][1]["n"] == 42


def test_validate_unknown_role_becomes_other() -> None:
    parsed = {
        "groups": [{"label": "Weird", "role": "xenobait", "criteria": "?"}],
        "design_type": "cohort",
    }
    out = cd._validate(parsed)
    assert out["groups"][0]["role"] == "other"


def test_validate_unknown_design_type_becomes_unknown() -> None:
    parsed = {
        "groups": [{"label": "G", "role": "case", "criteria": "x"}],
        "design_type": "made_up_design",
    }
    out = cd._validate(parsed)
    assert out["design_type"] == "unknown"


def test_validate_drops_groups_with_no_label() -> None:
    parsed = {
        "groups": [
            {"label": "", "role": "case", "criteria": "x"},
            {"label": "Valid", "role": "case", "criteria": "y"},
        ],
        "design_type": "cohort",
    }
    out = cd._validate(parsed)
    assert len(out["groups"]) == 1
    assert out["groups"][0]["label"] == "Valid"


def test_validate_n_coercion() -> None:
    parsed = {
        "groups": [
            {"label": "A", "role": "case", "n": "30", "criteria": "x"},
            {"label": "B", "role": "case", "n": -5, "criteria": "x"},
            {"label": "C", "role": "case", "n": True, "criteria": "x"},
            {"label": "D", "role": "case", "n": "notanint", "criteria": "x"},
        ],
        "design_type": "cohort",
    }
    out = cd._validate(parsed)
    assert out["groups"][0]["n"] == 30  # string → int
    assert out["groups"][1]["n"] is None  # negative → None
    assert out["groups"][2]["n"] is None  # bool → None
    assert out["groups"][3]["n"] is None


def test_validate_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        cd._validate(["not", "object"])  # type: ignore[arg-type]


def test_validate_truncates_long_fields() -> None:
    parsed = {
        "groups": [{"label": "L" * 200, "role": "case", "criteria": "C" * 1000}],
        "design_type": "cohort",
        "notes": "N" * 1000,
    }
    out = cd._validate(parsed)
    assert len(out["groups"][0]["label"]) == 60
    assert len(out["groups"][0]["criteria"]) == 200
    assert len(out["notes"]) == 400
