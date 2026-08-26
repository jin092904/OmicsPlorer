"""CL-in-tissue 정리: tissue_ids 의 CL(세포) 코드를 cell_type_ids 로 이동(dedup) 후
변경된 레코드의 Qdrant payload + OpenSearch doc 를 부분 갱신(tissue_ids/cell_type_ids만).

- 매퍼 가드는 이미 수정(b5900dc) → 재발 없음. 기존 3,900건 일회성 정리.
- UPDATE ... RETURNING 으로 '정확히 바뀐 레코드'만 잡아 색인 갱신(과다갱신 없음).
- 부분갱신이라 벡터/기타필드 무영향. 멱등(재실행 시 대상 0).
실행: PGURL=<dsn> QDRANT_URL=.. OPENSEARCH_URL=.. apps/workers/.venv/bin/python .../fix_cl_in_tissue.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import asyncpg
import httpx

QDRANT = os.environ.get("QDRANT_URL", "http://localhost:6333")
OS_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
COLL = "datasets_v2"


async def main() -> None:
    pg = await asyncpg.connect(os.environ["PGURL"])
    rows = await pg.fetch(
        """
        update datasets set
          cell_type_ids = (
            select array_agg(distinct z)
            from unnest(coalesce(cell_type_ids, '{}') ||
                        array(select y from unnest(tissue_ids) y where y like 'CL:%')) z),
          tissue_ids = array(select y from unnest(tissue_ids) y where y not like 'CL:%')
        where exists(select 1 from unnest(tissue_ids) x where x like 'CL:%')
        returning id, tissue_ids, cell_type_ids
        """
    )
    await pg.close()
    print(f"DB UPDATE: {len(rows)}건 (tissue의 CL → cell 이동)", flush=True)
    if not rows:
        print("변경 없음(이미 깨끗).")
        return

    async with httpx.AsyncClient(timeout=60.0) as c:
        # 1) Qdrant payload 부분갱신 (dataset_id 필터로 해당 point 의 tissue/cell 만 set)
        q_ok = 0
        for r in rows:
            did = str(r["id"])
            body = {
                "payload": {
                    "tissue_ids": list(r["tissue_ids"] or []),
                    "cell_type_ids": list(r["cell_type_ids"] or []),
                },
                "filter": {"must": [{"key": "dataset_id", "match": {"value": did}}]},
            }
            resp = await c.post(f"{QDRANT}/collections/{COLL}/points/payload?wait=true", json=body)
            resp.raise_for_status()
            q_ok += 1
            if q_ok % 1000 == 0:
                print(f"  Qdrant {q_ok}/{len(rows)}", flush=True)
        print(f"Qdrant payload 갱신: {q_ok}", flush=True)

        # 2) OpenSearch doc 부분갱신 (_bulk update)
        lines: list[str] = []
        for r in rows:
            did = str(r["id"])
            lines.append(json.dumps({"update": {"_index": COLL, "_id": did}}))
            lines.append(json.dumps({"doc": {
                "tissue_ids": list(r["tissue_ids"] or []),
                "cell_type_ids": list(r["cell_type_ids"] or []),
            }}))
        os_ok = 0
        for i in range(0, len(lines), 4000):
            chunk = "\n".join(lines[i : i + 4000]) + "\n"
            resp = await c.post(f"{OS_URL}/_bulk?refresh=false", content=chunk,
                                headers={"Content-Type": "application/x-ndjson"})
            resp.raise_for_status()
            j = resp.json()
            if j.get("errors"):
                for it in j.get("items", []):
                    st = it.get("update", {}).get("status", 200)
                    if st >= 300 and st != 404:
                        raise RuntimeError(f"OS bulk error: {it['update'].get('error')}")
            os_ok += len(chunk.strip().split("\n")) // 2
        await c.post(f"{OS_URL}/{COLL}/_refresh")
        print(f"OpenSearch doc 갱신: {os_ok}", flush=True)
    print("DONE — CL-in-tissue 정리 + 색인 반영 완료", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
