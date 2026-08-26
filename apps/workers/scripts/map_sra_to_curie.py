"""SRA 원문 온톨로지 용어 → CURIE 매핑 (track B, 2026-06-15 필드감사 후속).

문제: SRA 34만행(v3-phase3) 의 disease/tissue/cell_type 는 100% 원문 텍스트(CURIE 아님)라
      search.py 의 CURIE 필터/패싯에서 통째 누락된다(예: 'breast cancer' GEO 7,746 vs SRA 누락).

해법: distinct 원문 용어를 OLS4(exact match)로 CURIE 매핑(빈도순 top-N → 적은 호출로 큰 커버리지),
      term→curie 사전을 영속화(재실행 시 OLS4 재호출 X). --commit 시 SRA 행의 매핑된 원문을 CURIE로
      교체(중복 제거, 미매핑 원문은 fallback 유지) + 변경분 Qdrant/OS 동기화.

주의: 전수(disease 12k + tissue 6k distinct)는 다중 시간 OLS4 배치 + 부분 커버리지(식물/환경
      tissue=leaf/soil/root 는 UBERON 매핑 불가, 약어·generic 도 미스). 데모 필수 아님 → 스케줄 권장.

실행:
  cd apps/workers; DATABASE_URL=... QDRANT_URL=... OPENSEARCH_URL=... \\
  uv run python scripts/map_sra_to_curie.py --field disease --top 300 --dry-run   # 매핑+커버리지
  uv run python scripts/map_sra_to_curie.py --field disease --commit              # 적용+sync
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.indexer.embeddings import (  # noqa: E402
    ensure_collection,
    get_qdrant_client,
)
from src.indexer.embeddings import (
    refresh_payloads as qdrant_refresh_payloads,
)
from src.indexer.lexical import (  # noqa: E402
    ensure_index,
    get_os_client,
)
from src.indexer.lexical import (
    upsert_many as os_upsert_many,
)
from src.ontology.mapper import OntologyMapper  # noqa: E402

log = logging.getLogger("map-sra-curie")
DICT_DIR = ROOT.parent.parent / "logs"
SYNC_BATCH = 2000  # bulk timeout 여유(견고화)

FIELD_ONTO = {"disease": ("disease_ids", "mondo"), "tissue": ("tissue_ids", "uberon"),
              "cell_type": ("cell_type_ids", "cl")}
# 기대 CURIE prefix — OLS4 가 exact 로 타 온톨로지(예: sepsis→HP) 를 반환해도 거른다(쓰레기 재주입 방지).
ONTO_PREFIX = {"mondo": "MONDO:", "uberon": "UBERON:", "cl": "CL:"}


def _dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _is_curie(v: str) -> bool:
    import re
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9_]*:[0-9]", v))


async def _distinct_terms(pg: asyncpg.Connection, col: str, sources: list[str], top: int | None) -> list[tuple[str, int]]:
    q = (f"SELECT lower(btrim(x)) term, count(*) n FROM datasets d, unnest(d.{col}) x "
         f"WHERE d.source_db = ANY($1) AND x !~ '^[A-Za-z]+:[0-9]' GROUP BY 1 ORDER BY 2 DESC")
    if top:
        q += f" LIMIT {int(top)}"
    return [(r["term"], r["n"]) for r in await pg.fetch(q, sources)]


async def _build_dict(terms: list[tuple[str, int]], onto: str, concurrency: int,
                      seed: dict[str, str] | None = None) -> dict[str, str]:
    """term -> curie (매핑 실패/타-온톨로지는 제외). 동시성 제한 + 매퍼 LRU.

    seed: 기존(이전 실행) term→curie 사전. 이미 있는 term 은 OLS4 재호출 생략(GEO·재실행 가속).
    """
    mapping: dict[str, str] = dict(seed or {})
    prefix = ONTO_PREFIX[onto]
    todo = [t for t, _ in terms if t not in mapping]
    sem = asyncio.Semaphore(concurrency)
    async with OntologyMapper() as mapper:
        async def one(term: str) -> None:
            async with sem:
                try:
                    m = await mapper.lookup(term, onto)  # type: ignore[arg-type]
                except Exception:
                    m = None
            # 기대 온톨로지 prefix 만 채택(sepsis→HP 같은 교차온톨로지 오매핑 배제).
            if m is not None and m.curie.upper().startswith(prefix):
                mapping[term] = m.curie
        await asyncio.gather(*(one(t) for t in todo))
    return mapping


def _apply(values: list[str], mapping: dict[str, str]) -> list[str]:
    """매핑된 원문 → CURIE 교체(중복제거, 순서보존), 미매핑은 원문 유지."""
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        nv = v
        if not _is_curie(v):
            c = mapping.get(v.strip().lower())
            if c:
                nv = c
        if nv not in seen:
            seen.add(nv)
            out.append(nv)
    return out


FETCH_SQL = """
SELECT id, source_db, source_id, title, abstract, modality, organism_taxid,
       disease_ids, tissue_ids, cell_type_ids, access_type, has_processed_data,
       submission_date, n_samples, n_subjects, platform, library_strategy, extraction_version
  FROM datasets WHERE id = ANY($1::uuid[])
"""


async def run(*, field: str, top: int | None, commit: bool, concurrency: int,
              sources: list[str]) -> dict[str, Any]:
    col, onto = FIELD_ONTO[field]
    pg = await asyncpg.connect(_dsn())
    try:
        terms = await _distinct_terms(pg, col, sources, top)
        total_occ = sum(n for _, n in terms)
        log.info("%s [%s]: %d distinct terms (occ=%d) to map via OLS4(%s)",
                 field, ",".join(sources), len(terms), total_occ, onto)
        DICT_DIR.mkdir(parents=True, exist_ok=True)
        dictpath = DICT_DIR / f"sra_curie_map_{field}.json"
        seed: dict[str, str] = {}
        if dictpath.exists():
            try:
                seed = json.loads(dictpath.read_text(encoding="utf-8"))
                log.info("seed dict: %d terms (OLS4 재호출 생략)", len(seed))
            except Exception:
                seed = {}
        mapping = await _build_dict(terms, onto, concurrency, seed=seed)
        mapped_occ = sum(n for t, n in terms if t in mapping)
        dictpath.write_text(json.dumps(mapping, ensure_ascii=False, indent=0), encoding="utf-8")
        cov = (mapped_occ / total_occ * 100) if total_occ else 0
        log.info("mapped %d/%d terms; occurrence coverage %.1f%% (dict: %s)",
                 len(mapping), len(terms), cov, dictpath)

        if not commit:
            sample = list(mapping.items())[:10]
            for t, cval in sample:
                log.info("   %s -> %s", t, cval)
            return {"dry_run": True, "field": field, "terms": len(terms),
                    "mapped_terms": len(mapping), "occ_coverage_pct": round(cov, 1)}

        # apply to rows that contain any raw (non-curie) term in the field
        rows = await pg.fetch(
            f"SELECT id, {col} AS vals FROM datasets WHERE source_db = ANY($1) AND {col} IS NOT NULL "
            f"AND EXISTS(SELECT 1 FROM unnest({col}) x WHERE x !~ '^[A-Za-z]+:[0-9]')", sources)
        changed: list[str] = []
        async with pg.transaction():
            for r in rows:
                old = list(r["vals"] or [])
                new = _apply(old, mapping)
                if new != old:
                    await pg.execute(f"UPDATE datasets SET {col} = $2 WHERE id = $1::uuid", r["id"], new)
                    changed.append(str(r["id"]))
        log.info("applied: %d rows changed", len(changed))
        if not changed:
            return {"changed": 0, "field": field, "occ_coverage_pct": round(cov, 1)}
    finally:
        if not commit:
            await pg.close()

    qdrant = get_qdrant_client()
    os_client = get_os_client()
    qn = on = 0
    try:
        await ensure_collection(qdrant)
        await ensure_index(os_client)
        for i in range(0, len(changed), SYNC_BATCH):
            batch = changed[i:i + SYNC_BATCH]
            rd = [dict(r) for r in await pg.fetch(FETCH_SQL, batch)]
            qn += await qdrant_refresh_payloads(qdrant, rd)
            on += await os_upsert_many(os_client, rd)
            log.info("synced %d/%d", min(i + SYNC_BATCH, len(changed)), len(changed))
    finally:
        await qdrant.close()
        await os_client.close()
        await pg.close()
    log.info("DONE %s: changed=%d coverage=%.1f%%", field, len(changed), cov)
    return {"changed": len(changed), "field": field, "occ_coverage_pct": round(cov, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--field", choices=list(FIELD_ONTO), required=True)
    ap.add_argument("--source", default="SRA", help="SRA | GEO | SRA,GEO (기본 SRA)")
    ap.add_argument("--top", type=int, default=0, help="빈도 상위 N 용어만(0=전체)")
    ap.add_argument("--concurrency", type=int, default=8)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sources = [s.strip() for s in args.source.split(",") if s.strip()]
    print(asyncio.run(run(field=args.field, top=(args.top or None), commit=args.commit,
                          concurrency=args.concurrency, sources=sources)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
