"""Load the real-data GEO demo into PostgreSQL and Qdrant.

The asset holds accessions, derived fields, and stored vectors, but no titles or summaries. They
are fetched from NCBI E-utilities here, together with the PubMed abstracts that the full corpus
appended to short summaries (see ``pubmed_augment_short_abstracts.py``). Run
``reindex_lexical.py`` afterwards. Requests stay under three per second unless ``NCBI_API_KEY``
is set.
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
import struct
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from pubmed_augment_short_abstracts import fetch_pubmed_batch
from qdrant_client.models import PointStruct
from sqlalchemy import text

from src.db import get_engine
from src.indexer.embeddings import (
    COLLECTION_NAME,
    EMBED_DIM,
    _payload,
    ensure_collection,
    get_qdrant_client,
)

ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
DEMO_PROFILE = "geo-v1"
ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/jin092904/OmicsPlorer/demo-geo")

INSERT_SQL = text("""
INSERT INTO datasets (
  id, source_db, source_id, title, abstract, modality, organism_taxid, n_samples, n_subjects,
  disease_ids, tissue_ids, cell_type_ids, access_type, has_processed_data, platform,
  library_strategy, submission_date, raw_metadata, extraction_version
) VALUES (
  :id, 'GEO', :source_id, :title, :abstract, :modality, :organism_taxid, :n_samples, :n_subjects,
  :disease_ids, :tissue_ids, :cell_type_ids, :access_type, :has_processed_data, :platform,
  :library_strategy, :submission_date, CAST(:raw_metadata AS jsonb), :extraction_version
)
ON CONFLICT (source_db, source_id) DO UPDATE SET
  title = EXCLUDED.title, abstract = EXCLUDED.abstract, modality = EXCLUDED.modality,
  organism_taxid = EXCLUDED.organism_taxid, n_samples = EXCLUDED.n_samples,
  n_subjects = EXCLUDED.n_subjects, disease_ids = EXCLUDED.disease_ids,
  tissue_ids = EXCLUDED.tissue_ids, cell_type_ids = EXCLUDED.cell_type_ids,
  access_type = EXCLUDED.access_type, has_processed_data = EXCLUDED.has_processed_data,
  platform = EXCLUDED.platform, library_strategy = EXCLUDED.library_strategy,
  submission_date = EXCLUDED.submission_date, raw_metadata = EXCLUDED.raw_metadata,
  extraction_version = EXCLUDED.extraction_version, updated_at = now()
-- Rows that were not written by this demo (for example, harvested records) are left untouched.
WHERE datasets.raw_metadata->>'demo_profile' = EXCLUDED.raw_metadata->>'demo_profile'
RETURNING id
""")


# Demo rows from an earlier load whose Series this run could not fetch or excluded. They are
# reported, not deleted, because other tables may already refer to them.
EARLIER_ROWS_SQL = text("""
SELECT count(*) FROM datasets
WHERE source_db = 'GEO' AND source_id = ANY(:accessions)
  AND raw_metadata->>'demo_profile' = :profile
""")


def demo_id(accession: str) -> uuid.UUID:
    """Deterministic identifier so PostgreSQL rows and Qdrant points always agree."""
    return uuid.uuid5(ID_NAMESPACE, accession)


def gds_uid(accession: str) -> str:
    """GEO Series GSEnnn is UID 200000000 + nnn in the NCBI gds database."""
    if not accession.startswith("GSE") or not accession[3:].isdigit():
        raise ValueError(f"not a GEO Series accession: {accession}")
    return str(200_000_000 + int(accession[3:]))


def read_asset(path: Path, manifest: Path) -> list[dict[str, Any]]:
    if not manifest.is_file():
        raise SystemExit(f"demo asset manifest not found: {manifest}")
    expected = json.loads(manifest.read_text())["sha256"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"demo asset checksum mismatch: expected {expected}, got {actual}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def ncbi_api_key() -> str | None:
    return os.environ.get("NCBI_API_KEY") or os.environ.get("NCBI_EUTILS_API_KEY") or None


def parse_esummary(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """esummary (db=gds, JSON) result -> accession -> {"title", "summary", "pmid"}."""
    found: dict[str, dict[str, Any]] = {}
    for uid in result.get("uids", []):
        item = result.get(uid) or {}
        accession = item.get("accession")
        title = (item.get("title") or "").strip()
        if accession and title:
            pmids = item.get("pubmedids") or []
            found[accession] = {"title": title, "summary": item.get("summary") or "",
                                "pmid": str(pmids[0]) if pmids else None}
    return found


async def _esummary(client: httpx.AsyncClient, accessions: list[str], api_key: str | None) -> dict[str, Any]:
    data = {"db": "gds", "retmode": "json", "tool": "omicsplorer-demo",
            "id": ",".join(gds_uid(a) for a in accessions)}
    if api_key:
        data["api_key"] = api_key
    error: Exception | None = None
    for attempt in range(4):
        if attempt:
            await asyncio.sleep(2 ** (attempt - 1))
        try:
            response = await client.post(ESUMMARY, data=data)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            error = exc
            continue
        if "result" in payload:
            return payload["result"]
        if "esummaryresult" in payload:  # NCBI has no document for these IDs, e.g. "Invalid uid"
            return {"uids": []}
        error = ValueError(f"unexpected esummary answer: {str(payload)[:200]}")
    raise SystemExit(f"NCBI esummary failed after retries: {error}")


async def fetch_summaries(accessions: list[str], batch: int) -> dict[str, dict[str, Any]]:
    """GEO Series accession -> {"title", "summary", "pmid"} from NCBI esummary (db=gds).

    Accessions missing from an answer are asked for again in batches of 20, then one by one, so
    one withdrawn Series does not hide the rest of its batch.
    """
    api_key = ncbi_api_key()
    interval = 0.12 if api_key else 0.4
    found: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=60) as client:
        for size in (batch, 20, 1):
            pending = [accession for accession in accessions if accession not in found]
            for start in range(0, len(pending), size):
                found.update(parse_esummary(await _esummary(client, pending[start:start + size], api_key)))
                print(f"ncbi: {len(found)}/{len(accessions)}", file=sys.stderr)
                await asyncio.sleep(interval)
    return found


async def fetch_pubmed_abstracts(pmids: list[str], batch: int = 200) -> dict[str, str]:
    """PubMed ID -> abstract, fetched with the full-corpus code; missing IDs are asked for again."""
    api_key = ncbi_api_key()
    interval = 0.12 if api_key else 0.4
    found: dict[str, str] = {}
    async with httpx.AsyncClient(headers={"User-Agent": "OmicsPlorer demo loader"}, timeout=60) as client:
        for size in (batch, 20, 1):
            pending = [pmid for pmid in pmids if pmid not in found]
            for start in range(0, len(pending), size):
                found.update(await _efetch_with_retries(client, pending[start:start + size], api_key))
                await asyncio.sleep(interval)
    return found


async def _efetch_with_retries(client: httpx.AsyncClient, pmids: list[str], api_key: str | None) -> dict[str, str]:
    # An unparsable answer comes back as {}; its IDs stay pending for the next, smaller round.
    error: Exception | None = None
    for attempt in range(4):
        if attempt:
            await asyncio.sleep(2 ** (attempt - 1))
        try:
            return await fetch_pubmed_batch(client, pmids, api_key)
        except httpx.HTTPError as exc:
            error = exc
    raise SystemExit(f"PubMed efetch failed after retries: {error}")


def append_abstracts(records: list[dict[str, Any]], texts: dict[str, dict[str, Any]],
                     abstracts: dict[str, str]) -> tuple[int, list[str]]:
    """Append each record's PubMed abstract as the full corpus did; return (count, unavailable IDs)."""
    appended, unavailable = 0, set()
    for record in records:
        pmid = record.get("abstract_pubmed_pmid")
        accession = record["source_id"]
        if not pmid or accession not in texts:
            continue
        pmid = str(pmid)
        if pmid not in abstracts:
            unavailable.add(pmid)
            continue
        original = texts[accession]["summary"].strip()
        # Same format as scripts/pubmed_augment_short_abstracts.py.
        if original and original.lower() not in ("data", "test", "abstract", "1"):
            texts[accession]["summary"] = f"{original}\n\n[PubMed PMID:{pmid}] {abstracts[pmid]}"
        else:
            texts[accession]["summary"] = f"[PubMed PMID:{pmid}] {abstracts[pmid]}"
        appended += 1
    return appended, sorted(unavailable)


def partition_records(records: list[dict[str, Any]], texts: dict[str, dict[str, Any]],
                      missing_pmids: list[str]) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]],
                                                         list[str], list[str]]:
    """Split records into (loadable, missing on NCBI, excluded).

    A record whose PubMed abstract could not be fetched is excluded: its text would no longer match
    the text its stored vector was computed from.
    """
    unrestored = {str(pmid) for pmid in missing_pmids}
    kept, missing, excluded = [], [], []
    for record in records:
        accession = record["source_id"]
        if accession not in texts:
            missing.append(accession)
        elif str(record.get("abstract_pubmed_pmid") or "") in unrestored:
            excluded.append(accession)
        else:
            kept.append((record, texts[accession]))
    return kept, sorted(missing), sorted(excluded)


def row_for(record: dict[str, Any], text: dict[str, Any]) -> dict[str, Any]:
    submission = record.get("submission_date")
    return {
        "id": demo_id(record["source_id"]),
        "source_id": record["source_id"],
        "title": text["title"],
        "abstract": text["summary"].strip() or None,
        "modality": record.get("modality") or [],
        "organism_taxid": record.get("organism_taxid") or [],
        "n_samples": record.get("n_samples"),
        "n_subjects": record.get("n_subjects"),
        "disease_ids": record.get("disease_ids") or [],
        "tissue_ids": record.get("tissue_ids") or [],
        "cell_type_ids": record.get("cell_type_ids") or [],
        "access_type": record.get("access_type") or "open",
        "has_processed_data": bool(record.get("has_processed_data")),
        "platform": record.get("platform"),
        "library_strategy": record.get("library_strategy"),
        "submission_date": dt.date.fromisoformat(submission) if submission else None,
        "raw_metadata": json.dumps({"demo_profile": DEMO_PROFILE,
                                    "text_source": "NCBI E-utilities esummary (db=gds)",
                                    "in_blinded_pool": bool(record.get("in_blinded_pool"))}),
        "extraction_version": record.get("extraction_version") or "demo",
    }


def vector_of(record: dict[str, Any]) -> list[float]:
    raw = base64.b64decode(record["vector_f32_b64"])
    if len(raw) != EMBED_DIM * 4:
        raise SystemExit(f"unexpected vector size for {record['source_id']}: {len(raw)} bytes")
    return list(struct.unpack(f"<{EMBED_DIM}f", raw))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None,
                        help="manifest JSON whose sha256 the asset must match "
                             "(default: the .manifest.json next to the asset)")
    parser.add_argument("--ncbi-batch", type=int, default=200)
    parser.add_argument("--max-missing", type=int, default=25,
                        help="stop before writing if more records than this cannot be loaded because "
                             "NCBI no longer returns them (a few Series are withdrawn over time)")
    args = parser.parse_args()

    manifest = args.manifest or args.asset.with_name(args.asset.name.replace(".jsonl.gz", ".manifest.json"))
    records = read_asset(args.asset, manifest)
    texts = await fetch_summaries([r["source_id"] for r in records], args.ncbi_batch)
    wanted_pmids = sorted({str(r["abstract_pubmed_pmid"]) for r in records
                           if r.get("abstract_pubmed_pmid") and r["source_id"] in texts})
    augmented, missing_pmids = append_abstracts(records, texts, await fetch_pubmed_abstracts(wanted_pmids))

    kept, missing, excluded = partition_records(records, texts, missing_pmids)
    if len(missing) + len(excluded) > args.max_missing:
        raise SystemExit(
            f"NCBI did not return {len(missing)} GEO Series and {len(missing_pmids)} PubMed records "
            f"(limit {args.max_missing} records in total); nothing was written. Retry later, or raise "
            f"--max-missing if these records were withdrawn. First missing: {missing[:10]} {missing_pmids[:10]}"
        )

    written: list[tuple[dict[str, Any], dict[str, Any]]] = []
    skipped_existing = 0
    engine = get_engine()
    try:
        async with engine.begin() as connection:
            earlier_rows = (await connection.execute(
                EARLIER_ROWS_SQL, {"accessions": missing + excluded, "profile": DEMO_PROFILE},
            )).scalar_one()
            for record, text in kept:
                row = row_for(record, text)
                row_id = (await connection.execute(INSERT_SQL, row)).scalar_one_or_none()
                if row_id is None:
                    skipped_existing += 1
                    continue
                row["id"] = row_id  # the Qdrant point uses the PostgreSQL id
                written.append((record, row))
    finally:
        await engine.dispose()

    qdrant = get_qdrant_client()
    try:
        await ensure_collection(qdrant)
        points: list[PointStruct] = []
        for record, row in written:
            payload_row = {**row, "source_db": "GEO", "extraction_lineage_id": None, "build_stage": None}
            points.append(PointStruct(id=str(row["id"]), vector=vector_of(record),
                                      payload=_payload(payload_row)))
        for start in range(0, len(points), 256):
            await qdrant.upsert(collection_name=COLLECTION_NAME, points=points[start:start + 256])
    finally:
        await qdrant.close()

    print(json.dumps({
        "demo_profile": DEMO_PROFILE,
        "records_in_asset": len(records),
        "loaded": len(written),
        "skipped_existing_non_demo_rows": skipped_existing,
        "summaries_with_pubmed_abstract": augmented,
        "pubmed_abstracts_unavailable": len(missing_pmids),
        "excluded_without_pubmed_abstract": excluded,
        "missing_on_ncbi": len(missing),
        "missing_examples": missing[:10],
        "earlier_demo_rows_not_refreshed": earlier_rows,
        "qdrant_collection": COLLECTION_NAME,
        "fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
