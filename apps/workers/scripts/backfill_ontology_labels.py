"""S4: CURIE → 사람이 읽는 라벨 백필 (③⑤ 색인 본문 보강의 선행).

datasets 의 disease_ids/tissue_ids/cell_type_ids 에 들어있는 distinct CURIE
(MONDO/UBERON/CL/EFO)를 OLS4 정확매칭으로 라벨 해석해 JSON 파일로 적재.

- prod DB 는 읽기(SELECT)만 — 앱 role 은 DDL 권한이 없으므로 결과는 JSON 파일에 저장.
- 미스(라벨 없음)도 null 로 기록 → 재실행 시 재조회 방지(resume).
- 동시성 제한(SEM)으로 OLS4 rate-limit 회피.

출력: ONTOLOGY_LABELS_PATH (기본 apps/workers/data/ontology_labels.json)
실행: PGURL=<dsn> apps/workers/.venv/bin/python apps/workers/scripts/backfill_ontology_labels.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg
import httpx

OLS4 = "https://www.ebi.ac.uk/ols4/api"
ONTO_OK = {"mondo", "uberon", "cl", "efo"}
SEM = asyncio.Semaphore(10)
OUT_PATH = Path(
    os.environ.get(
        "ONTOLOGY_LABELS_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "ontology_labels.json"),
    )
)


async def lookup(client: httpx.AsyncClient, curie: str) -> tuple[str, str | None]:
    onto = curie.split(":", 1)[0].lower()
    if onto not in ONTO_OK:
        return curie, None
    async with SEM:
        try:
            r = await client.get(
                "/search",
                params={"q": curie, "ontology": onto, "rows": 1, "exact": "true"},
            )
            r.raise_for_status()
            docs = (r.json().get("response", {}) or {}).get("docs") or []
            label = docs[0].get("label") if docs else None
            return curie, (label if isinstance(label, str) and label else None)
        except Exception:
            return curie, None


async def main() -> None:
    pg = await asyncpg.connect(os.environ["PGURL"])
    rows = await pg.fetch(
        """
        select distinct c from (
          select unnest(disease_ids) c from datasets
          union all select unnest(tissue_ids) from datasets
          union all select unnest(cell_type_ids) from datasets
        ) t where c ~ '^(MONDO|UBERON|CL|EFO):'
        """
    )
    await pg.close()
    all_curies = [r["c"] for r in rows]

    # resume: 기존 결과(라벨/미스 모두) 로드
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    have: dict[str, str | None] = {}
    if OUT_PATH.exists():
        have = json.loads(OUT_PATH.read_text())
    todo = [c for c in all_curies if c not in have]
    print(f"distinct CURIE={len(all_curies)} already={len(have)} todo={len(todo)}", flush=True)

    done = 0
    async with httpx.AsyncClient(base_url=OLS4, timeout=20.0) as client:
        for i in range(0, len(todo), 200):
            chunk = todo[i : i + 200]
            res = await asyncio.gather(*(lookup(client, c) for c in chunk))
            for c, label in res:
                have[c] = label
            OUT_PATH.write_text(json.dumps(have, ensure_ascii=False, indent=0))
            done += len(chunk)
            labeled = sum(1 for v in have.values() if v)
            print(f"  {done}/{len(todo)} processed, {labeled} labeled total", flush=True)

    labeled = sum(1 for v in have.values() if v)
    print(f"DONE — {OUT_PATH}: total={len(have)} labeled={labeled} miss={len(have) - labeled}", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
