"""Phase 1 — Backfill bioproject_id + dataset_sources from existing raw_metadata.

NCBI EUtils 호출 0건 — 모든 데이터가 GEO raw_metadata 의 esummary 응답 안에 이미 있음
(bioproject + extrelations[type=SRA]).

작업:
  1. datasets.bioproject_id 채우기 (GEO raw_metadata → bioproject)
  2. dataset_sources 에 GEO primary ref 인서트 (모든 GEO 28만 건)
  3. dataset_sources 에 SRA secondary ref 인서트 (extrelations 에 SRA 링크 있는 8만 건)
  4. dataset_sources 에 GDC primary ref 인서트 (GDC 91 건)

소요: postgres SQL UPDATE/INSERT — 약 5-15분.

산출 (`/tmp/genofinder-phase1-report.json`):
  - bioproject coverage
  - SRA cross-ref by modality + by gdstype
  - 매칭 unique BioProject 수 (Phase 2 의 dedup 후보군)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

REPORT_PATH = Path("/tmp/genofinder-phase1-report.json")


def _pg_dsn() -> str:
    # ALEMBIC_DATABASE_URL 은 owner 권한 (DDL/UPDATE 가능). DATABASE_URL 은 NOSUPERUSER app role.
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("ALEMBIC_DATABASE_URL or DATABASE_URL must be set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def step1_backfill_bioproject(conn: asyncpg.Connection) -> int:
    """GEO datasets 의 bioproject_id 컬럼을 raw_metadata 에서 추출해 채움."""
    log.info("step 1 — populating datasets.bioproject_id from raw_metadata.bioproject")
    t0 = time.perf_counter()
    res = await conn.execute(
        """
        UPDATE datasets
        SET bioproject_id =
          raw_metadata->'result'->(raw_metadata->'result'->'uids'->>0)->>'bioproject'
        WHERE source_db = 'GEO'
          AND bioproject_id IS NULL
          AND (raw_metadata->'result'->(raw_metadata->'result'->'uids'->>0)->>'bioproject') <> ''
        """
    )
    n = int(res.split()[-1])
    log.info("  updated %d rows in %.1fs", n, time.perf_counter() - t0)
    return n


async def step2_insert_geo_primary(conn: asyncpg.Connection) -> int:
    log.info("step 2 — inserting GEO primary source refs")
    t0 = time.perf_counter()
    res = await conn.execute(
        """
        INSERT INTO dataset_sources
          (dataset_id, source_db, source_id, raw_url, is_primary, linked_via)
        SELECT
          id,
          'GEO',
          source_id,
          'https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=' || source_id,
          TRUE,
          'original'
        FROM datasets
        WHERE source_db = 'GEO'
        ON CONFLICT (dataset_id, source_db, source_id) DO NOTHING
        """
    )
    n = int(res.split()[-1])
    log.info("  inserted %d rows in %.1fs", n, time.perf_counter() - t0)
    return n


async def step3_insert_sra_from_extrelations(conn: asyncpg.Connection) -> int:
    log.info("step 3 — inserting SRA cross-refs from GEO extrelations")
    t0 = time.perf_counter()
    res = await conn.execute(
        """
        INSERT INTO dataset_sources
          (dataset_id, source_db, source_id, raw_url, is_primary, linked_via)
        SELECT
          d.id,
          'SRA',
          rel->>'targetobject',
          rel->>'targetftplink',
          FALSE,
          'extrelations'
        FROM datasets d,
        LATERAL jsonb_array_elements(
          COALESCE(
            d.raw_metadata->'result'->(d.raw_metadata->'result'->'uids'->>0)->'extrelations',
            '[]'::jsonb
          )
        ) rel
        WHERE d.source_db = 'GEO'
          AND rel->>'relationtype' = 'SRA'
          AND rel->>'targetobject' IS NOT NULL
          AND rel->>'targetobject' <> ''
        ON CONFLICT (dataset_id, source_db, source_id) DO NOTHING
        """
    )
    n = int(res.split()[-1])
    log.info("  inserted %d rows in %.1fs", n, time.perf_counter() - t0)
    return n


async def step4_insert_gdc_primary(conn: asyncpg.Connection) -> int:
    log.info("step 4 — inserting GDC primary source refs")
    t0 = time.perf_counter()
    res = await conn.execute(
        """
        INSERT INTO dataset_sources
          (dataset_id, source_db, source_id, raw_url, is_primary, linked_via)
        SELECT
          id,
          'GDC',
          source_id,
          'https://portal.gdc.cancer.gov/projects/' || source_id,
          TRUE,
          'original'
        FROM datasets
        WHERE source_db = 'GDC'
        ON CONFLICT (dataset_id, source_db, source_id) DO NOTHING
        """
    )
    n = int(res.split()[-1])
    log.info("  inserted %d rows in %.1fs", n, time.perf_counter() - t0)
    return n


async def step5_report(conn: asyncpg.Connection) -> dict:
    """Phase 2 결정용 분석 리포트."""
    log.info("step 5 — generating Phase 1 analysis report")

    coverage = await conn.fetchrow(
        """
        SELECT
          COUNT(*) AS total_geo,
          COUNT(bioproject_id) AS with_bioproject,
          COUNT(DISTINCT bioproject_id) AS unique_bioprojects
        FROM datasets WHERE source_db='GEO'
        """
    )

    sra_coverage = await conn.fetchrow(
        """
        SELECT
          COUNT(DISTINCT dataset_id) AS geo_with_sra
        FROM dataset_sources WHERE source_db='SRA'
        """
    )

    sra_by_gdstype = await conn.fetch(
        """
        WITH labeled AS (
          SELECT
            d.id,
            d.raw_metadata->'result'->(d.raw_metadata->'result'->'uids'->>0)->>'gdstype' AS gdstype,
            EXISTS (
              SELECT 1 FROM dataset_sources ds
              WHERE ds.dataset_id = d.id AND ds.source_db='SRA'
            ) AS has_sra
          FROM datasets d WHERE d.source_db='GEO'
        )
        SELECT
          COALESCE(gdstype, '(null)') AS gdstype,
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE has_sra) AS with_sra,
          ROUND(100.0 * COUNT(*) FILTER (WHERE has_sra) / COUNT(*), 1) AS pct_sra
        FROM labeled
        GROUP BY gdstype
        ORDER BY total DESC
        LIMIT 15
        """
    )

    sra_by_modality = await conn.fetch(
        """
        WITH labeled AS (
          SELECT
            d.id,
            unnest(d.modality) AS modality,
            EXISTS (
              SELECT 1 FROM dataset_sources ds
              WHERE ds.dataset_id = d.id AND ds.source_db='SRA'
            ) AS has_sra
          FROM datasets d WHERE d.source_db='GEO'
        )
        SELECT
          modality,
          COUNT(*) AS total,
          COUNT(*) FILTER (WHERE has_sra) AS with_sra,
          ROUND(100.0 * COUNT(*) FILTER (WHERE has_sra) / COUNT(*), 1) AS pct_sra
        FROM labeled
        GROUP BY modality
        ORDER BY total DESC
        LIMIT 21
        """
    )

    sample_refs = await conn.fetch(
        """
        SELECT d.source_id AS gse, d.bioproject_id,
          array_agg(ds.source_id || '|' || ds.source_db ORDER BY ds.source_db) AS sources
        FROM datasets d
        JOIN dataset_sources ds ON ds.dataset_id = d.id
        WHERE d.source_db='GEO'
        GROUP BY d.id
        HAVING COUNT(*) > 1
        LIMIT 10
        """
    )

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total_geo": coverage["total_geo"],
        "geo_with_bioproject": coverage["with_bioproject"],
        "unique_bioprojects": coverage["unique_bioprojects"],
        "bioproject_coverage_pct": round(
            100.0 * coverage["with_bioproject"] / coverage["total_geo"], 2
        ),
        "geo_with_sra_link": sra_coverage["geo_with_sra"],
        "sra_link_pct": round(
            100.0 * sra_coverage["geo_with_sra"] / coverage["total_geo"], 2
        ),
        "by_gdstype": [
            {
                "gdstype": r["gdstype"],
                "total": r["total"],
                "with_sra": r["with_sra"],
                "pct_sra": float(r["pct_sra"]),
            }
            for r in sra_by_gdstype
        ],
        "by_modality": [
            {
                "modality": r["modality"],
                "total": r["total"],
                "with_sra": r["with_sra"],
                "pct_sra": float(r["pct_sra"]),
            }
            for r in sra_by_modality
        ],
        "examples_with_multiple_sources": [
            {"gse": r["gse"], "bioproject": r["bioproject_id"], "sources": list(r["sources"])}
            for r in sample_refs
        ],
    }
    return report


async def main() -> None:
    log.info("Phase 1 backfill starting — connecting to postgres")
    conn = await asyncpg.connect(_pg_dsn())
    try:
        n1 = await step1_backfill_bioproject(conn)
        n2 = await step2_insert_geo_primary(conn)
        n3 = await step3_insert_sra_from_extrelations(conn)
        n4 = await step4_insert_gdc_primary(conn)
        report = await step5_report(conn)

        report["counts"] = {
            "bioproject_updated": n1,
            "geo_primary_inserted": n2,
            "sra_cross_ref_inserted": n3,
            "gdc_primary_inserted": n4,
        }

        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        log.info("=" * 60)
        log.info("✅ Phase 1 backfill complete")
        log.info("  bioproject_id 채워진 GEO: %d", n1)
        log.info("  GEO primary refs:        %d", n2)
        log.info("  SRA cross-ref:           %d", n3)
        log.info("  GDC primary:             %d", n4)
        log.info("  bioproject coverage:     %.2f%%", report["bioproject_coverage_pct"])
        log.info("  GEO with SRA link:       %.2f%%", report["sra_link_pct"])
        log.info("  unique BioProjects:      %d", report["unique_bioprojects"])
        log.info("  report → %s", REPORT_PATH)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
