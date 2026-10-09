"""Export the real-data GEO demo subset from a full OmicsPlorer corpus (read-only).

Selection: the GEO Series listed in ``--judged`` that have a stored vector, then other GEO Series
in md5(seed || accession) order until ``--target`` records. Each record keeps the accession,
derived fields, the stored vector, and the PubMed ID whose abstract the corpus appended to the
summary; no titles, summaries, or internal IDs are written.

Environment: DATABASE_URL, QDRANT_URL, and optionally OLLAMA_URL with OLLAMA_MODEL_EMBED to record
the embedding model digest in the manifest.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import struct
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from qdrant_client import AsyncQdrantClient

COLLECTION = "datasets_v2"
EMBED_DIM = 1024
FIELDS = r"""source_id, modality, organism_taxid, n_samples, n_subjects, disease_ids, tissue_ids,
            cell_type_ids, access_type, has_processed_data, platform, library_strategy,
            submission_date, extraction_version,
            substring(abstract from '\[PubMed PMID:([0-9]+)\]') AS abstract_pubmed_pmid"""


def asyncpg_url(url: str) -> str:
    return re.sub(r"^postgresql\+[a-z0-9]+://", "postgresql://", url)


async def stored_vectors(qdrant: AsyncQdrantClient, rows: list[asyncpg.Record]) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    ids = [str(row["id"]) for row in rows]
    for start in range(0, len(ids), 256):
        points = await qdrant.retrieve(COLLECTION, ids=ids[start:start + 256],
                                       with_vectors=True, with_payload=False)
        for point in points:
            found[str(point.id)] = point.vector
    return found


async def embedding_model_digest() -> dict[str, Any] | None:
    url, model = os.environ.get("OLLAMA_URL"), os.environ.get("OLLAMA_MODEL_EMBED")
    if not url or not model:
        return None
    async with httpx.AsyncClient(timeout=30) as client:
        tags = (await client.get(f"{url.rstrip('/')}/api/tags")).json()
        version = (await client.get(f"{url.rstrip('/')}/api/version")).json().get("version")
    for item in tags.get("models", []):
        if item.get("name") == model:
            return {"ollama_tag": model, "ollama_digest": item.get("digest"),
                    "quantization": (item.get("details") or {}).get("quantization_level"),
                    "ollama_version": version}
    return None


def record_line(row: asyncpg.Record, vector: list[float], in_pool: bool) -> str:
    return json.dumps({
        "source_id": row["source_id"],
        "abstract_pubmed_pmid": row["abstract_pubmed_pmid"],
        "modality": list(row["modality"] or []),
        "organism_taxid": list(row["organism_taxid"] or []),
        "n_samples": row["n_samples"],
        "n_subjects": row["n_subjects"],
        "disease_ids": list(row["disease_ids"] or []),
        "tissue_ids": list(row["tissue_ids"] or []),
        "cell_type_ids": list(row["cell_type_ids"] or []),
        "access_type": row["access_type"],
        "has_processed_data": bool(row["has_processed_data"]),
        "platform": row["platform"],
        "library_strategy": row["library_strategy"],
        "submission_date": row["submission_date"].isoformat() if row["submission_date"] else None,
        "extraction_version": row["extraction_version"],
        "in_blinded_pool": in_pool,
        "vector_f32_b64": base64.b64encode(struct.pack(f"<{EMBED_DIM}f", *vector)).decode(),
    }, ensure_ascii=False, sort_keys=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--judged", type=Path, required=True,
                        help="text file of GEO Series accessions to include first")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--name", default="omicsplorer-demo-geo-v1")
    parser.add_argument("--seed", default="omicsplorer-demo-geo-v1")
    parser.add_argument("--target", type=int, default=5000)
    args = parser.parse_args()

    judged = sorted({x.strip() for x in args.judged.read_text().split() if x.strip()})
    connection = await asyncpg.connect(asyncpg_url(os.environ["DATABASE_URL"]))
    try:
        await connection.execute("SET default_transaction_read_only = on")
        judged_rows = await connection.fetch(
            f"SELECT id, {FIELDS} FROM datasets WHERE source_db='GEO' AND source_id = ANY($1::text[])",
            judged,
        )
        fill_rows = await connection.fetch(
            f"""SELECT id, {FIELDS} FROM datasets
                 WHERE source_db='GEO' AND NOT (source_id = ANY($1::text[]))
                 ORDER BY md5($2 || source_id) LIMIT $3""",
            judged, args.seed, args.target * 2,
        )
    finally:
        await connection.close()

    qdrant = AsyncQdrantClient(url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"), timeout=120)
    try:
        judged_vectors = await stored_vectors(qdrant, judged_rows)
        fill_vectors = await stored_vectors(qdrant, fill_rows)
    finally:
        await qdrant.close()

    selected = [(row, judged_vectors[str(row["id"])], True)
                for row in judged_rows if str(row["id"]) in judged_vectors]
    judged_kept = len(selected)
    for row in fill_rows:
        if len(selected) >= args.target:
            break
        if str(row["id"]) in fill_vectors:
            selected.append((row, fill_vectors[str(row["id"])], False))
    if {len(vector) for _, vector, _ in selected} != {EMBED_DIM}:
        raise SystemExit("unexpected vector dimension in the selected records")

    lines = [record_line(row, vector, in_pool)
             for row, vector, in_pool in sorted(selected, key=lambda item: item[0]["source_id"])]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    asset = args.out_dir / f"{args.name}.jsonl.gz"
    with gzip.GzipFile(asset, "wb", mtime=0) as handle:
        handle.write(("\n".join(lines) + "\n").encode())

    manifest = {
        "artifact": asset.name,
        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
        "bytes": asset.stat().st_size,
        "records": len(lines),
        "records_in_blinded_pool": judged_kept,
        "judged_geo_series_total": len(judged),
        "selection": "judged GEO Series present with a stored vector, then md5(seed || accession) order",
        "seed": args.seed,
        "vector": {
            "dim": EMBED_DIM,
            "dtype": "float32 little-endian, base64",
            "text": "title + summary + library_strategy/platform, as composed by "
                    "apps/workers/src/indexer/embeddings.py",
            "model": await embedding_model_digest(),
        },
        "records_with_pubmed_abstract": sum(1 for row, _, _ in selected if row["abstract_pubmed_pmid"]),
        "excluded": ["titles", "summaries", "abstracts", "raw submitter metadata",
                     "internal dataset identifiers"],
        "exported_on": dt.date.today().isoformat(),
    }
    (args.out_dir / f"{args.name}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
