"""S6/Option D: 격리 OpenSearch 인덱스 datasets_v2_exp 구성 (라벨/디자인 본문 증강).

prod datasets_v2 는 손대지 않고, 새 인덱스에 기존 필드 + 신규 text 필드
  - labels      : disease/tissue/cell 의 사람-읽는 라벨(CURIE→ontology_labels.json) + free-text + modality
  - design_text : cohort_design(design_type + group label/criteria)
를 넣어 BM25 A/B 의 exp arm 을 만든다. GPU 불필요(임베딩 미사용).

가역: 인덱스 이름이 *_exp 라 prod 무영향. 실패/철회 시 인덱스 DROP 만.
실행: PGURL=<dsn> apps/workers/.venv/bin/python apps/workers/scripts/build_exp_os_index.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg
import httpx

SRC_INDEX = "datasets_v2"
EXP_INDEX = "datasets_v2_exp"
LABELS_PATH = Path(__file__).resolve().parents[1] / "data" / "ontology_labels.json"

# prod 매핑(lexical.py INDEX_BODY)과 동일 + labels/design_text(text) 2개만 추가. (불신: 원본과 어긋나면
# 비교가 오염되므로 동일 properties 유지하고 신규 2필드만 얹음 — 가역.)
EXP_INDEX_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "analysis": {"analyzer": {"default": {"type": "standard", "stopwords": "_english_"}}},
    },
    "mappings": {
        "dynamic": "strict",
        "properties": {
            "dataset_id": {"type": "keyword"},
            "source_db": {"type": "keyword"},
            "source_id": {"type": "text", "analyzer": "standard", "fields": {"keyword": {"type": "keyword"}}},
            "title": {"type": "text"},
            "abstract": {"type": "text"},
            "labels": {"type": "text"},          # 신규
            "design_text": {"type": "text"},      # 신규
            "modality": {"type": "keyword"},
            "organism_taxid": {"type": "integer"},
            "disease_ids": {"type": "keyword"},
            "tissue_ids": {"type": "keyword"},
            "cell_type_ids": {"type": "keyword"},
            "access_type": {"type": "keyword"},
            "has_processed_data": {"type": "boolean"},
            "platform": {"type": "keyword"},
            "library_strategy": {"type": "keyword"},
            "submission_date": {"type": "date"},
            "n_samples": {"type": "integer"},
            "n_subjects": {"type": "integer"},
            "extraction_version": {"type": "keyword"},
        },
    },
}

SELECT_SQL = """
SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
       disease_ids, tissue_ids, cell_type_ids, access_type, has_processed_data,
       platform, library_strategy, submission_date, n_samples, n_subjects,
       extraction_version, cohort_design
FROM datasets
ORDER BY id
"""


def _labels_text(row, label_map: dict) -> str:
    parts: list[str] = []
    for key in ("disease_ids", "tissue_ids", "cell_type_ids"):
        for v in row.get(key) or []:
            v = str(v)
            if ":" in v:  # CURIE → 라벨(있으면). 없으면(미해석) 스킵(노이즈/무의미 CURIE 문자열 방지).
                lab = label_map.get(v)
                if lab:
                    parts.append(lab)
            else:  # free-text 라벨(예: 'peripheral blood', 'leaves') 그대로
                if v.strip():
                    parts.append(v.strip())
    for m in row.get("modality") or []:
        if str(m).strip():
            parts.append(str(m).strip())
    return " | ".join(dict.fromkeys(parts))  # dedup, 순서보존


def _design_text(row) -> str:
    cd = row.get("cohort_design")
    if isinstance(cd, str):
        try:
            cd = json.loads(cd or "{}")
        except Exception:
            return ""
    if not isinstance(cd, dict):
        return ""
    dt = cd.get("design_type")
    if not dt or dt == "unknown":
        return ""
    parts = [str(dt).replace("_", " ")]
    for g in cd.get("groups") or []:
        if not isinstance(g, dict):
            continue
        for kk in ("label", "criteria"):
            if g.get(kk):
                parts.append(str(g[kk]))
    return " | ".join(dict.fromkeys(parts))


def _src(d: dict, labels: str, dtext: str) -> dict:
    return {
        "dataset_id": str(d["id"]),
        "source_db": d["source_db"],
        "source_id": d["source_id"],
        "title": d.get("title"),
        "abstract": d.get("abstract"),
        "labels": labels or None,
        "design_text": dtext or None,
        "modality": d.get("modality") or [],
        "organism_taxid": d.get("organism_taxid") or [],
        "disease_ids": d.get("disease_ids") or [],
        "tissue_ids": d.get("tissue_ids") or [],
        "cell_type_ids": d.get("cell_type_ids") or [],
        "access_type": d["access_type"],
        "has_processed_data": bool(d.get("has_processed_data", False)),
        "platform": d.get("platform"),
        "library_strategy": d.get("library_strategy"),
        "submission_date": d["submission_date"].isoformat() if d.get("submission_date") else None,
        "n_samples": d.get("n_samples"),
        "n_subjects": d.get("n_subjects"),
        "extraction_version": d.get("extraction_version"),
    }


async def _flush(client: httpx.AsyncClient, lines: list[str]) -> int:
    if not lines:
        return 0
    body = "\n".join(lines) + "\n"
    r = await client.post("/_bulk", content=body, headers={"Content-Type": "application/x-ndjson"})
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        # 첫 에러만 노출(불신: 조용한 실패 금지)
        for it in j.get("items", []):
            st = it.get("index", {}).get("status", 200)
            if st >= 300:
                raise RuntimeError(f"bulk error: {it['index'].get('error')}")
    return len(j.get("items", []))


async def main() -> None:
    if not LABELS_PATH.exists():
        print(f"FATAL: labels JSON 없음 {LABELS_PATH} — S4 백필 먼저", flush=True)
        sys.exit(2)
    label_map = {k: v for k, v in json.loads(LABELS_PATH.read_text()).items() if v}
    print(f"labels loaded: {len(label_map)}", flush=True)

    os_url = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
    client = httpx.AsyncClient(base_url=os_url, timeout=180.0)
    # 멱등: 기존 exp 인덱스 삭제 후 재생성(가역).
    await client.delete(f"/{EXP_INDEX}")  # 없으면 404 → 무시
    r = await client.put(f"/{EXP_INDEX}", json=EXP_INDEX_BODY)
    r.raise_for_status()
    print(f"created {EXP_INDEX}", flush=True)

    pg = await asyncpg.connect(os.environ["PGURL"])
    n = n_lab = n_design = indexed = 0
    lines: list[str] = []
    async with pg.transaction():
        async for row in pg.cursor(SELECT_SQL):
            d = dict(row)
            labels = _labels_text(d, label_map)
            dtext = _design_text(d)
            n += 1
            if labels:
                n_lab += 1
            if dtext:
                n_design += 1
            lines.append(json.dumps({"index": {"_index": EXP_INDEX, "_id": str(d["id"])}}))
            lines.append(json.dumps(_src(d, labels, dtext), ensure_ascii=False, default=str))
            if len(lines) >= 4000:  # 2000 docs/배치
                indexed += await _flush(client, lines)
                lines = []
                if indexed % 40000 == 0:
                    print(f"  indexed {indexed} (seen {n}, labels {n_lab}, design {n_design})", flush=True)
    indexed += await _flush(client, lines)
    await pg.close()
    await client.post(f"/{EXP_INDEX}/_refresh")
    cnt = (await client.get(f"/{EXP_INDEX}/_count")).json().get("count")
    await client.aclose()
    print(f"DONE — indexed={indexed} docs_seen={n} with_labels={n_lab} "
          f"with_design={n_design} exp_count={cnt}", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
