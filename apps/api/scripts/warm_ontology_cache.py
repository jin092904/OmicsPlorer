"""자주 쓰일 만한 ontology curie 의 라벨을 미리 in-memory cache 에 채워둔다.

사용 시점:
    - API 기동 후 첫 /search 응답 시 facet 라벨이 즉시 표시됨 (외부 호출 0회).
    - DB 의 disease_ids/tissue_ids/cell_type_ids 컬럼에서 unique 모은 후 lookup_labels 호출.
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from src.services.ontology import lookup_labels


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        async with eng.connect() as conn:
            result = await conn.execute(text("""
                SELECT DISTINCT unnest(disease_ids || tissue_ids || cell_type_ids) AS curie
                  FROM datasets
                 WHERE array_length(disease_ids,1) > 0
                    OR array_length(tissue_ids,1) > 0
                    OR array_length(cell_type_ids,1) > 0
            """))
            curies = [r[0] for r in result.fetchall()]
        print(f"warming {len(curies)} unique ontology curies...")
        if curies:
            labels = await lookup_labels(curies)
            print(f"  resolved {len(labels)} labels (rest: unknown / OLS4 미매칭)")
            # sample 출력
            for c, lbl in list(labels.items())[:5]:
                print(f"  {c:25s} → {lbl}")
    finally:
        await eng.dispose()


if __name__ == "__main__":
    asyncio.run(main())
