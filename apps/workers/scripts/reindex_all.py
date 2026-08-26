"""Synchronous container entrypoint for the full DB→Qdrant/OpenSearch reindex."""
from __future__ import annotations

import asyncio
import json

from src.db import get_engine
from src.indexer.pipeline import reindex_all_search_layers


async def main() -> int:
    engine = get_engine()
    try:
        result = await reindex_all_search_layers(engine)
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
