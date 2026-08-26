"""Sample indexer — GeoMatrixHarvester 의 sample dict 들을 samples 테이블에 UPSERT.

호출 순서:
    matrix = await GeoMatrixHarvester().fetch_samples(gse)
    await index_samples(conn, dataset_id, matrix)

멱등성: (dataset_id, source_sample_id) UNIQUE 제약 (alembic 0001) 위에서 UPSERT.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# raw_attributes 안에서 administrative 필드는 그룹 변수 후보가 아님.
# api/src/services/cohort_samples.py 의 _FACTOR_EXCLUDE_KEYS 와 sync 유지.
_FACTOR_EXCLUDE_KEYS = {
    "Sample_status", "Sample_submission_date", "Sample_last_update_date",
    "Sample_type", "Sample_channel_count", "Sample_source_name_ch1",
    "Sample_organism_ch1", "Sample_taxid_ch1", "Sample_molecule_ch1",
    "Sample_data_row_count", "Sample_data_processing", "Sample_description",
    "Sample_platform_id", "Sample_instrument_model", "Sample_library_strategy",
    "Sample_library_source", "Sample_library_selection",
    "Sample_extract_protocol_ch1", "Sample_growth_protocol_ch1",
    "Sample_treatment_protocol_ch1", "Sample_label_ch1", "Sample_label_protocol_ch1",
    "Sample_hyb_protocol", "Sample_scan_protocol", "Sample_title", "Sample_relation",
    "Sample_contact_name", "Sample_contact_email", "Sample_contact_phone",
    "Sample_contact_address", "Sample_contact_city", "Sample_contact_state",
    "Sample_contact_country", "Sample_contact_zip/postal_code",
    "Sample_contact_institute", "Sample_contact_department",
    "Sample_supplementary_file_1", "Sample_supplementary_file_2",
}

# 별도 extraction_version 은 두지 않음 — samples 는 source 의 원본 characteristics 를
# 보존하는 레이어. 추출 로직이 바뀌면 raw_attributes 를 재parse 하면 된다.


async def index_samples(
    conn: AsyncConnection,
    dataset_id: UUID,
    samples: list[dict[str, Any]],
) -> int:
    """sample dict 리스트 → samples 테이블 UPSERT. 반환값은 영향 받은 row 수.

    각 dict 키:
        source_sample_id (필수)
        sex, age_value, age_unit, disease_state, treatment (모두 nullable)
        raw_attributes (dict — JSONB 로 직렬화)
    """
    if not samples:
        return 0

    sql = text("""
        INSERT INTO samples (
            dataset_id, source_sample_id,
            sex, age_value, age_unit, disease_state, treatment,
            raw_attributes
        ) VALUES (
            :dataset_id, :source_sample_id,
            :sex, :age_value, :age_unit, :disease_state, :treatment,
            CAST(:raw_attributes AS jsonb)
        )
        ON CONFLICT ON CONSTRAINT uq_samples_source DO UPDATE SET
            sex            = EXCLUDED.sex,
            age_value      = EXCLUDED.age_value,
            age_unit       = EXCLUDED.age_unit,
            disease_state  = EXCLUDED.disease_state,
            treatment      = EXCLUDED.treatment,
            raw_attributes = EXCLUDED.raw_attributes
    """)
    written = 0
    for s in samples:
        if not s.get("source_sample_id"):
            continue
        await conn.execute(
            sql,
            {
                "dataset_id": dataset_id,
                "source_sample_id": s["source_sample_id"],
                "sex": s.get("sex"),
                "age_value": s.get("age_value"),
                "age_unit": s.get("age_unit"),
                "disease_state": s.get("disease_state"),
                "treatment": s.get("treatment"),
                "raw_attributes": json.dumps(s.get("raw_attributes") or {}),
            },
        )
        written += 1
    return written


async def fetch_samples_summary(
    conn: AsyncConnection,
    dataset_id: UUID,
) -> dict[str, Any]:
    """samples 테이블에서 데이터셋의 코호트 분포 집계.

    반환:
        {
            "n_total": int,
            "sex": {"male": int, "female": int, "unknown": int},
            "age": {
                "unit": "year"|"month"|"day"|None,
                "min": float|None, "max": float|None, "median": float|None,
                "buckets": [{"lo": int, "hi": int, "count": int}, ...]  # 5종 bucket
            },
            "disease_state": [{"label": str, "count": int}, ...]  # top 10
            "treatment":     [{"label": str, "count": int}, ...]  # top 10
        }

    sample 이 없으면 n_total=0 + 빈 분포. 본 함수는 시각화 컴포넌트가 직접 호출하는 핫패스 —
    가능하면 단일 쿼리로 GROUP BY.
    """
    # 1) 성별 분포 — NULL 도 unknown 으로 묶음.
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
    sex_dist = {r["sex"]: int(r["n"]) for r in sex_rows}
    # canonical 키 보장
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

    # 2) 연령 — unit 이 섞이면 가장 흔한 unit 기준. min/max/median + 5종 bucket.
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

    # 3) disease_state / treatment 라벨 분포 — top 10.
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
    # 컬럼명 화이트리스트 — SQL injection 차단.
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

    Canonical impl 은 api/src/services/cohort_samples.py — 본 모듈은 workers batch
    경로용 동일 로직 복제 (cross-package import 회피). 두 구현은 같은 결과를 내야 함.

    반환:
        {
            "varying":  [{"factor", "values":[{"value","count"}, ...]}, ...],
            "constant": [{"factor", "value", "count"}, ...],
        }
    """
    result = await conn.execute(
        text("SELECT raw_attributes FROM samples WHERE dataset_id = :did"),
        {"did": dataset_id},
    )
    rows = result.mappings().all()
    if not rows:
        return {"varying": [], "constant": []}

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

    varying.sort(key=lambda x: -len(x["values"]))
    constant.sort(key=lambda x: x["factor"])
    return {"varying": varying[:6], "constant": constant[:8]}


def _summarize_age(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"unit": None, "min": None, "max": None, "median": None, "buckets": []}

    # 가장 흔한 unit — 다른 unit 은 무시 (정규화 사전이 day/year/month 만 발급).
    unit_counts: dict[str, int] = {}
    for r in rows:
        u = r["age_unit"] or "year"
        unit_counts[u] = unit_counts.get(u, 0) + 1
    main_unit = max(unit_counts.items(), key=lambda kv: kv[1])[0]
    values = sorted(float(r["age_value"]) for r in rows if (r["age_unit"] or "year") == main_unit)
    if not values:
        return {"unit": None, "min": None, "max": None, "median": None, "buckets": []}

    lo = values[0]
    hi = values[-1]
    median = values[len(values) // 2] if len(values) % 2 else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2
    # 5종 bucket (균등 분할)
    span = hi - lo
    if span == 0:
        buckets = [{"lo": int(lo), "hi": int(hi), "count": len(values)}]
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
