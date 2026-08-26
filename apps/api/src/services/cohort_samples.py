"""samples 테이블 집계 — API hot path (cohort 시각화).

workers/src/indexer/samples.py 의 fetch_samples_summary 와 동일한 출력 형태이지만,
api side 는 자체 DB 연결을 통해 호출되므로 별도 모듈로 둔다 (workers 패키지 의존을
api 에 끌어들이지 않기 위해).
"""
from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

# raw_attributes 안에서 "메타" 키 (sample 자체의 식별/제출 정보)는 그룹 변수 후보가 아니므로
# factor 집계에서 제외한다. Series Matrix 의 Sample_* 필드는 GSM/날짜/제출자 같은 administrative
# 정보라 그룹 분리와 무관.
_FACTOR_EXCLUDE_KEYS = {
    "Sample_status",
    "Sample_submission_date",
    "Sample_last_update_date",
    "Sample_type",
    "Sample_channel_count",
    "Sample_source_name_ch1",
    "Sample_organism_ch1",
    "Sample_taxid_ch1",
    "Sample_molecule_ch1",
    "Sample_data_row_count",
    "Sample_data_processing",
    "Sample_description",
    "Sample_platform_id",
    "Sample_instrument_model",
    "Sample_library_strategy",
    "Sample_library_source",
    "Sample_library_selection",
    "Sample_extract_protocol_ch1",
    "Sample_growth_protocol_ch1",
    "Sample_treatment_protocol_ch1",
    "Sample_label_ch1",
    "Sample_label_protocol_ch1",
    "Sample_hyb_protocol",
    "Sample_scan_protocol",
    "Sample_title",
    "Sample_relation",
    "Sample_contact_name",
    "Sample_contact_email",
    "Sample_contact_phone",
    "Sample_contact_address",
    "Sample_contact_city",
    "Sample_contact_state",
    "Sample_contact_country",
    "Sample_contact_zip/postal_code",
    "Sample_contact_institute",
    "Sample_contact_department",
    "Sample_supplementary_file_1",
    "Sample_supplementary_file_2",
}


async def summarize_samples(conn: AsyncConnection, dataset_id: UUID) -> dict[str, Any]:
    """samples 테이블 → {n_total, sex, age, disease_state, treatment}."""
    # 1) sex
    result = await conn.execute(
        text("""
            SELECT COALESCE(sex, 'unknown') AS sex, count(*) AS n
              FROM samples
             WHERE dataset_id = :did
          GROUP BY 1
        """),
        {"did": dataset_id},
    )
    sex_rows = result.mappings().all()
    sex_dist: dict[str, int] = {r["sex"]: int(r["n"]) for r in sex_rows}
    for k in ("male", "female", "unknown"):
        sex_dist.setdefault(k, 0)
    n_total = sum(sex_dist.values())

    if n_total == 0:
        return {
            "n_total": 0,
            "sex": sex_dist,
            "age": {"unit": None, "min": None, "max": None, "median": None, "buckets": []},
            "disease_state": [],
            "treatment": [],
        }

    # 2) age
    result = await conn.execute(
        text("""
            SELECT age_unit, age_value
              FROM samples
             WHERE dataset_id = :did AND age_value IS NOT NULL
        """),
        {"did": dataset_id},
    )
    age_rows = result.mappings().all()
    age_summary = _summarize_age(age_rows)

    # 3) label tops
    disease_dist = await _label_top(conn, dataset_id, "disease_state")
    treatment_dist = await _label_top(conn, dataset_id, "treatment")

    return {
        "n_total": n_total,
        "sex": sex_dist,
        "age": age_summary,
        "disease_state": disease_dist,
        "treatment": treatment_dist,
    }


async def _label_top(
    conn: AsyncConnection,
    dataset_id: UUID,
    column: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    if column not in {"disease_state", "treatment"}:
        raise ValueError(f"unsupported column: {column!r}")
    sql = text(
        f"""
            SELECT {column} AS label, count(*) AS n
              FROM samples
             WHERE dataset_id = :did AND {column} IS NOT NULL
          GROUP BY {column}
          ORDER BY n DESC, label ASC
             LIMIT :lim
        """
    )
    result = await conn.execute(sql, {"did": dataset_id, "lim": limit})
    return [{"label": r["label"], "count": int(r["n"])} for r in result.mappings().all()]


async def fetch_sample_factors(
    conn: AsyncConnection,
    dataset_id: UUID,
) -> dict[str, list[dict[str, Any]]]:
    """samples.raw_attributes 에서 그룹 변수 후보 추출.

    반환:
        {
            "varying":  [{"factor": "age", "values": [{"value":"12-weeks","count":7}, ...]}, ...],
            "constant": [{"factor": "sex", "value": "Male", "count": 14}, ...],
        }

    - varying: sample 마다 값이 2 종 이상 다른 키 (= 그룹 변수 후보). LLM 이 이 정보로
      cohort 구조 파악.
    - constant: 모든 sample 이 같은 값인 키. context 로 유용 (e.g., "all male, all Heart").
    - _FACTOR_EXCLUDE_KEYS 의 administrative 필드는 모두 제외.

    raw_attributes 가 비어있거나 samples 가 0건이면 빈 dict.
    """
    result = await conn.execute(
        text("SELECT raw_attributes FROM samples WHERE dataset_id = :did"),
        {"did": dataset_id},
    )
    rows = result.mappings().all()
    if not rows:
        return {"varying": [], "constant": []}

    # key → Counter(value → count)
    key_value_counts: dict[str, Counter[str]] = {}
    for row in rows:
        attrs = row["raw_attributes"] or {}
        if not isinstance(attrs, dict):
            continue
        for k, v in attrs.items():
            if k in _FACTOR_EXCLUDE_KEYS:
                continue
            if not isinstance(v, str) or not v.strip():
                continue
            key_value_counts.setdefault(k, Counter())[v] += 1

    varying: list[dict[str, Any]] = []
    constant: list[dict[str, Any]] = []
    for k, counter in key_value_counts.items():
        if len(counter) == 1:
            value, count = next(iter(counter.items()))
            constant.append({"factor": k, "value": value, "count": count})
        else:
            values = [{"value": v, "count": c} for v, c in counter.most_common(8)]
            varying.append({"factor": k, "values": values})

    # 보기 좋은 순서: varying 은 분산 큰 순(고유 값 수), constant 는 이름 알파벳 순
    varying.sort(key=lambda x: -len(x["values"]))
    constant.sort(key=lambda x: x["factor"])
    return {"varying": varying[:6], "constant": constant[:8]}


def _summarize_age(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"unit": None, "min": None, "max": None, "median": None, "buckets": []}
    unit_counts: dict[str, int] = {}
    for r in rows:
        u = r["age_unit"] or "year"
        unit_counts[u] = unit_counts.get(u, 0) + 1
    main_unit = max(unit_counts.items(), key=lambda kv: kv[1])[0]
    values = sorted(
        float(r["age_value"]) for r in rows if (r["age_unit"] or "year") == main_unit
    )
    if not values:
        return {"unit": None, "min": None, "max": None, "median": None, "buckets": []}
    lo, hi = values[0], values[-1]
    n = len(values)
    median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
    span = hi - lo
    if span == 0:
        buckets = [{"lo": int(lo), "hi": int(hi), "count": n}]
    else:
        step = span / 5
        edges = [lo + step * i for i in range(6)]
        buckets = []
        for i in range(5):
            left, right = edges[i], edges[i + 1]
            cnt = sum(1 for v in values if (left <= v < right) or (i == 4 and v == right))
            buckets.append({"lo": round(left, 1), "hi": round(right, 1), "count": cnt})
    return {
        "unit": main_unit,
        "min": round(lo, 1),
        "max": round(hi, 1),
        "median": round(median, 1),
        "buckets": buckets,
    }
