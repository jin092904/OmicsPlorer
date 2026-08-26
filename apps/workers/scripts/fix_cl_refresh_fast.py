"""CL 정리 색인 refresh (빠른판) — DB 는 이미 수정됨. stale 색인만 DB 값으로 맞춘다.
stale 대상 = OpenSearch datasets_v2 에서 tissue_ids 에 CL:* 남은 doc(= 전체 3,900).
Qdrant set_payload(wait 없이·동시성16) + OpenSearch _bulk update. 멱등.
실행: PGURL=.. QDRANT_URL=.. OPENSEARCH_URL=.. .venv/bin/python .../fix_cl_refresh_fast.py
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
    async with httpx.AsyncClient(timeout=60.0) as c:
        # 1) stale doc id 수집: tissue_ids 에 CL:* prefix (keyword)
        stale_ids: list[str] = []
        body = {"size": 1000, "_source": False,
                "query": {"prefix": {"tissue_ids.keyword": "CL:"}}}
        # scroll 로 전부
        r = await c.post(f"{OS_URL}/{COLL}/_search?scroll=2m", json=body)
        r.raise_for_status()
        j = r.json()
        sid = j.get("_scroll_id")
        hits = j["hits"]["hits"]
        while hits:
            stale_ids.extend(h["_id"] for h in hits)
            r = await c.post(f"{OS_URL}/_search/scroll", json={"scroll": "2m", "scroll_id": sid})
            r.raise_for_status()
            j = r.json()
            sid = j.get("_scroll_id")
            hits = j["hits"]["hits"]
        print(f"stale(OS tissue에 CL) = {len(stale_ids)}", flush=True)
        if not stale_ids:
            print("stale 없음(이미 반영됨).")
            return

    # 2) DB 에서 이들의 현재(수정된) tissue/cell fetch
    pg = await asyncpg.connect(os.environ["PGURL"])
    recs = await pg.fetch(
        "select id, tissue_ids, cell_type_ids from datasets where id = any($1::uuid[])",
        stale_ids,
    )
    await pg.close()
    by_id = {str(r["id"]): (list(r["tissue_ids"] or []), list(r["cell_type_ids"] or [])) for r in recs}
    print(f"DB fetch = {len(by_id)}", flush=True)

    async with httpx.AsyncClient(timeout=15.0) as c:
        # 3) Qdrant set_payload (point-id, 저동시성4 + 재시도3 — 고동시성이 Qdrant write 불안정 유발)
        sem = asyncio.Semaphore(4)
        done = [0]

        async def q_set(did, tis, cell):
            async with sem:
                b = {"payload": {"tissue_ids": tis, "cell_type_ids": cell}, "points": [did]}
                for attempt in range(3):
                    try:
                        resp = await c.post(f"{QDRANT}/collections/{COLL}/points/payload", json=b)
                        resp.raise_for_status()
                        done[0] += 1
                        if done[0] % 500 == 0:
                            print(f"  Qdrant {done[0]}/{len(by_id)}", flush=True)
                        return
                    except Exception:
                        await asyncio.sleep(1 + attempt)
                print(f"  Qdrant FAIL {did}", flush=True)

        await asyncio.gather(*(q_set(did, t, cl) for did, (t, cl) in by_id.items()))
        print(f"Qdrant 갱신 {done[0]}/{len(by_id)}", flush=True)

        # 4) OpenSearch _bulk update
        lines = []
        for did, (t, cl) in by_id.items():
            lines.append(json.dumps({"update": {"_index": COLL, "_id": did}}))
            lines.append(json.dumps({"doc": {"tissue_ids": t, "cell_type_ids": cl}}))
        for i in range(0, len(lines), 4000):
            chunk = "\n".join(lines[i:i + 4000]) + "\n"
            resp = await c.post(f"{OS_URL}/_bulk?refresh=false", content=chunk,
                                headers={"Content-Type": "application/x-ndjson"})
            resp.raise_for_status()
        await c.post(f"{OS_URL}/{COLL}/_refresh")
        print(f"OpenSearch 갱신 {len(by_id)}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
