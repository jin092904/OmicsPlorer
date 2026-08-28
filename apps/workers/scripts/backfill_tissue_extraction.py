"""Sol4 tissue/cohort re-extraction backfill — fix paired-multi-tissue + subject-id blind spots.

목적 (2026-06-07):
  Phase 3 가 끝난 뒤 검증 결과, datasets.cardinality(tissue_ids) < 2 임에도 sample title
  레벨에서는 paired multi-tissue 가 명백한 케이스 (예: "Sample5-Urine-P1 / Sample5-Plasma-P1")
  가 다수 발견됨. 그리고 n_samples >= 4 인데 samples.subject_id 가 전부 NULL 인 row 가
  239,740 개 (38% of corpus) — paired/longitudinal 구조가 추출 단계에서 통째로 유실.

  본 스크립트는 weakness_score (paired/multi-tissue/cohort-design 키워드 일치 점수) 가
  높은 datasets 25k 건을 ordered priority 로 re-extract → tissue/cell_type/cohort_design/
  compound_flags 를 채워 paired-multi-tissue 등 compound query 정확도 향상.

격리:
  - 같은 메인 Ollama (11435) 사용 — Phase 3 와 GPU 경합 가능성은 watchdog 으로 완화.
  - postgres 만 write (datasets.tissue_ids/cell_type_ids/disease_ids/cohort_design/raw_metadata).
    Qdrant/OpenSearch 재인덱스는 별도 후속 step (reextract_with_ontology.py 의 reindex 부분).

체크포인트:
  /tmp/genofinder-sol4-checkpoint.json — {offset, inserted=0, updated, skipped, errors, started_at}.
  50 건마다 저장. SIGTERM/SIGINT 시 현재 dataset 처리 끝낸 뒤 저장 + exit 0.

CLI:
  --dry-run     candidate count + sample 3 건만 print, DB write 없음, LLM 호출 없음.
  --limit N     candidate 상한 (테스트용, default = 25000).
  --resume      checkpoint offset 부터 이어서.
  --batch-size  내부 직렬 처리 단위 (default 1 — gemma4:31b 가 GPU 무거워 직렬 권장).

호출 예 (실행):
  cd apps/workers
  OLLAMA_URL=http://localhost:11435 OLLAMA_MODEL_EXTRACTION=gemma4:31b \\
  DATABASE_URL=... uv run python scripts/backfill_tissue_extraction.py --limit 25000 --resume
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import httpx

# scripts/ 에서 직접 실행할 때 src/ import 가능하도록
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lineage import (  # noqa: E402
    BUILD_STAGE_MODEL_ENRICHED,
    composite_lineage_id,
    configured_lineage_id,
)

CHECKPOINT_PATH = Path("/tmp/genofinder-sol4-checkpoint.json")
REPORT_PATH = Path("/tmp/genofinder-sol4-report.json")
LOG_DIR = Path(os.environ.get("SOL4_LOG_DIR", str(ROOT / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / f"sol4-retag-{datetime.now().strftime('%Y%m%d')}.log"

# ─────────── Logger setup (file + stdout, timestamped) ───────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("sol4-retag")

# ─────────── Config ───────────
EXTRACTION_VERSION = "sol4-gemma4-2026-06-07"
SOL4_STAGE_LINEAGE_ID = configured_lineage_id("SOL4_EXTRACTION_LINEAGE_ID")
LINKED_VIA_MARKER = "sol4-retag"
LOG_EVERY = 50          # checkpoint save cadence
DEFAULT_LIMIT = 25_000
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11435")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL_EXTRACTION", "gemma4:31b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT_S", "180"))
LOCK_TTL_S = int(os.environ.get("SOL4_LOCK_TTL_S", "86400"))  # 24h

# Whitelist of well-known taxids (semantic check stage B-3b).
TAXID_WHITELIST = {9606, 10090, 10116, 7955, 7227, 6239, 4932, 3702, 9913, 9615, 9031, 8364}

# ─────────── Graceful shutdown ───────────
_should_stop = False


def _signal_handler(signum, frame):
    global _should_stop
    _should_stop = True
    log.warning("SIGNAL %s received — graceful stop after current dataset", signum)


def _install_signal_handlers() -> None:
    """SIGINT/SIGTERM 핸들러 설치. CLI(main thread)에선 정상 설치되고,
    Celery worker 가 이 모듈을 비-main thread 에서 import 할 때엔 조용히 패스
    (signal.signal 은 main thread 에서만 동작 → ValueError 방어)."""
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, RuntimeError) as e:  # non-main thread import
        log.warning("signal handlers not installed (likely non-main thread): %s", e)


_install_signal_handlers()


# ─────────── Circuit breaker config ───────────
CB_THRESHOLD = int(os.environ.get("SOL4_CB_THRESHOLD", "20"))
CB_MAX_RETRIES = int(os.environ.get("SOL4_OLLAMA_MAX_RETRIES", "5"))
CB_BACKOFF_CAP_S = 16.0


class InfrastructureError(Exception):
    """Raised by _ollama_generate when infrastructure retries are exhausted."""


# ─────────── Checkpoint helpers (mirrors Phase 3) ───────────
def _load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT_PATH.exists():
        try:
            return json.loads(CHECKPOINT_PATH.read_text())
        except json.JSONDecodeError:
            log.warning("checkpoint corrupted — starting fresh")
    return {
        "offset": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "started_at": time.time(),
    }


def _save_checkpoint(state: dict[str, Any]) -> None:
    CHECKPOINT_PATH.write_text(json.dumps(state, indent=2))


def _pg_dsn() -> str:
    url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ─────────── Candidate query (Strategy 4: Empty Subject-ID with Multi-Sample Studies) ───────────
PRIORITY_CANDIDATE_SQL = """
SELECT
  d.id,
  d.source_db,
  d.source_id,
  d.title,
  d.abstract,
  d.n_samples,
  d.raw_metadata,
  d.tissue_ids,
  d.cell_type_ids,
  d.disease_ids,
  d.cohort_design,
  d.extraction_lineage_id,
  (
    CASE WHEN d.title ILIKE '%paired%' OR d.title ILIKE '%matched%'
              OR d.abstract ILIKE '%paired%' OR d.abstract ILIKE '%matched%' THEN 1 ELSE 0 END
    +
    CASE WHEN d.raw_metadata::text ILIKE '%urine%' OR d.raw_metadata::text ILIKE '%stool%'
              OR d.raw_metadata::text ILIKE '%blood%' OR d.raw_metadata::text ILIKE '%liver%'
              OR d.raw_metadata::text ILIKE '%kidney%' OR d.raw_metadata::text ILIKE '%lung%'
              OR d.raw_metadata::text ILIKE '%brain%'
              OR d.abstract ILIKE '%urine%' OR d.abstract ILIKE '%stool%'
              OR d.abstract ILIKE '%blood%' OR d.abstract ILIKE '%liver%'
              OR d.abstract ILIKE '%kidney%' OR d.abstract ILIKE '%lung%'
              OR d.abstract ILIKE '%brain%' THEN 1 ELSE 0 END
    +
    CASE WHEN d.title ILIKE '%longitudinal%' OR d.title ILIKE '%cross-species%'
              OR d.title ILIKE '%multi-omics%' OR d.title ILIKE '%dose-response%'
              OR d.title ILIKE '%cohort%'
              OR d.abstract ILIKE '%longitudinal%' OR d.abstract ILIKE '%cross-species%'
              OR d.abstract ILIKE '%multi-omics%' OR d.abstract ILIKE '%dose-response%'
              OR d.abstract ILIKE '%cohort%' THEN 1 ELSE 0 END
  ) AS weakness_score
FROM datasets d
WHERE d.n_samples >= 4
  AND NOT EXISTS (
    SELECT 1 FROM samples s
    WHERE s.dataset_id = d.id
      AND s.subject_id IS NOT NULL
    LIMIT 1
  )
ORDER BY weakness_score DESC, d.n_samples DESC, d.id
OFFSET $1
LIMIT  $2
"""

CANDIDATE_COUNT_SQL = """
SELECT count(*) AS n
FROM datasets d
WHERE d.n_samples >= 4
  AND NOT EXISTS (
    SELECT 1 FROM samples s
    WHERE s.dataset_id = d.id
      AND s.subject_id IS NOT NULL
    LIMIT 1
  )
"""

SAMPLE_TITLES_SQL = """
SELECT source_sample_id, raw_attributes
FROM samples
WHERE dataset_id = $1
ORDER BY source_sample_id
LIMIT 30
"""


# ─────────── Prompt + schema (Sol4 spec) ───────────
SOL4_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Sol4ReExtractionResult",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "tissues", "cell_types", "organism_taxids", "diseases",
        "cohort_design", "subject_id_hint", "compound_flags", "notes",
    ],
    "properties": {
        "tissues": {
            "type": "array", "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 80,
                      "pattern": "^(?!UBERON:|CL:|MONDO:|EFO:|NCBITaxon:).+$"},
        },
        "cell_types": {
            "type": "array", "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 80,
                      "pattern": "^(?!UBERON:|CL:|MONDO:|EFO:|NCBITaxon:).+$"},
        },
        "organism_taxids": {
            "type": "array", "maxItems": 4,
            "items": {"type": "integer", "minimum": 1, "maximum": 9999999},
        },
        "diseases": {
            "type": "array", "maxItems": 8,
            "items": {"type": "string", "minLength": 1, "maxLength": 120,
                      "pattern": "^(?!UBERON:|CL:|MONDO:|EFO:|NCBITaxon:).+$"},
        },
        "cohort_design": {
            "type": "object", "additionalProperties": False,
            "required": ["design_type", "groups"],
            "properties": {
                "design_type": {
                    "type": "string",
                    "enum": ["paired", "longitudinal", "case_control", "cross_species",
                             "dose_response", "comparative", "cross_sectional", "unknown"],
                },
                "groups": {
                    "type": "array", "maxItems": 12,
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["label", "role", "n", "criteria"],
                        "properties": {
                            "label":    {"type": "string", "minLength": 1, "maxLength": 60},
                            "role":     {"type": "string",
                                         "enum": ["case", "control", "treatment", "comparison"]},
                            "n":        {"type": ["integer", "null"], "minimum": 0},
                            "criteria": {"type": "string", "maxLength": 200},
                        },
                    },
                },
            },
        },
        "subject_id_hint": {
            "type": "object", "additionalProperties": False,
            "required": ["applies", "pattern", "example"],
            "properties": {
                "applies": {"type": "boolean"},
                "pattern": {"type": ["string", "null"], "maxLength": 200},
                "example": {"type": ["string", "null"], "maxLength": 200},
            },
        },
        "compound_flags": {
            "type": "object", "additionalProperties": False,
            "required": ["paired_multi_tissue", "cell_type_x_tissue", "multi_organism",
                         "multi_omics", "dual_disease", "longitudinal", "dose_response"],
            "properties": {
                "paired_multi_tissue": {"type": "boolean"},
                "cell_type_x_tissue":  {"type": "boolean"},
                "multi_organism":      {"type": "boolean"},
                "multi_omics":         {"type": "boolean"},
                "dual_disease":        {"type": "boolean"},
                "longitudinal":        {"type": "boolean"},
                "dose_response":       {"type": "boolean"},
            },
        },
        "notes": {"type": "string", "maxLength": 300},
    },
}

# Prompt template lives in companion module; we import lazily so dry-run never touches it.
def _build_prompt(title: str, abstract: str, raw_metadata: str, sample_titles: list[str]) -> str:
    from sol4_prompt import SOL4_PROMPT_TEMPLATE  # type: ignore  # companion file
    numbered = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(sample_titles[:30])) or "  (none)"
    return (
        SOL4_PROMPT_TEMPLATE
        .replace("{{TITLE}}", title[:400] or "(no title)")
        .replace("{{ABSTRACT_TRUNCATED_2000_CHARS}}", (abstract or "")[:2000] or "(no abstract)")
        .replace("{{RAW_METADATA_TRUNCATED_4000_CHARS}}", raw_metadata[:4000] or "(none)")
        .replace("{{NUMBERED_SAMPLE_TITLES}}", numbered)
    )


# ─────────── LLM call w/ two-stage validate-and-retry (Stages A→D) ───────────
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _strip_code_fences(s: str) -> str:
    return _CODE_FENCE_RE.sub("", s).strip()


async def _ollama_generate(
    client: httpx.AsyncClient, prompt: str, *, temperature: float,
    max_retries: int = CB_MAX_RETRIES,
) -> dict | None:
    """Call ollama with infrastructure retry + model-output fail-fast.

    Returns:
        dict on success
        None on model-output failure (json decode / bad response shape) — caller treats
             this as a non-infrastructure semantic failure (does NOT count toward circuit
             breaker).

    Raises:
        InfrastructureError when max_retries on httpx ConnectError/TimeoutException/5xx
        are exhausted, OR when SIGTERM was received during backoff. Caller (harvest loop)
        must catch this and increment the circuit-breaker counter.
    """
    # WORKAROUND (2026-06-08): Ollama 0.23.3 has SchemaToGrammar SIGSEGV with
    # gemma4:31b + complex nested+enum schema. Omit format=schema; rely on prompt
    # JSON instructions + downstream _semantic_validate (jsonschema) for the contract.
    body = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "num_predict": 1024,
            "temperature": temperature,
            "top_p": 0.9,
            "num_ctx": 8192,
        },
    }

    last_infra_err: Exception | None = None
    for attempt in range(max_retries):
        if _should_stop:
            log.warning("ollama generate: SIGTERM observed before attempt %d — aborting", attempt + 1)
            raise InfrastructureError("aborted by SIGTERM before request")
        try:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate", json=body, timeout=OLLAMA_TIMEOUT
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            try:
                return json.loads(_strip_code_fences(raw))
            except json.JSONDecodeError as je:
                # Model-output failure — do NOT retry, do NOT trip circuit breaker.
                log.warning("ollama model output: JSONDecodeError: %s", str(je)[:160])
                return None
        except httpx.HTTPStatusError as he:
            status = he.response.status_code if he.response is not None else 0
            if 500 <= status < 600:
                last_infra_err = he
                log.warning(
                    "ollama infrastructure: HTTP %d (attempt %d/%d)",
                    status, attempt + 1, max_retries,
                )
            else:
                log.warning("ollama model output: HTTP %d (no retry): %s", status, str(he)[:160])
                return None
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError,
                httpx.ReadError, httpx.WriteError, httpx.PoolTimeout) as ne:
            last_infra_err = ne
            log.warning(
                "ollama infrastructure: %s: %s (attempt %d/%d)",
                type(ne).__name__, str(ne)[:160], attempt + 1, max_retries,
            )
        except Exception as e:
            # Unknown exception — treat as model-output failure (safer than infinite retry).
            log.warning("ollama model output: %s: %s", type(e).__name__, str(e)[:160])
            return None

        # Backoff before next attempt (1, 2, 4, 8, 16 s capped).
        if attempt < max_retries - 1:
            backoff = min(CB_BACKOFF_CAP_S, 2 ** attempt)
            await asyncio.sleep(backoff)
            if _should_stop:
                log.warning("ollama generate: SIGTERM observed after backoff — aborting retries")
                raise InfrastructureError("aborted by SIGTERM during backoff")

    log.error(
        "ollama generate: infrastructure retries exhausted (%d attempts): %s",
        max_retries, last_infra_err,
    )
    raise InfrastructureError(
        f"max_retries={max_retries} exhausted: {type(last_infra_err).__name__}: {last_infra_err}"
    )


def _semantic_validate(parsed: dict, sample_titles: list[str], raw_metadata: str) -> tuple[bool, str]:
    """Stage B semantic checks. Returns (ok, error_message)."""
    try:
        import jsonschema
        jsonschema.validate(parsed, SOL4_OUTPUT_SCHEMA)
    except Exception as e:
        return False, f"jsonschema: {str(e)[:160]}"

    # B-3a: CURIE defense-in-depth
    curie_re = re.compile(r"^(UBERON|CL|MONDO|EFO|NCBITaxon|HP|GO):", re.IGNORECASE)
    for key in ("tissues", "cell_types", "diseases"):
        for v in parsed.get(key, []):
            if curie_re.match(str(v)):
                return False, f"{key} contains CURIE-like '{v}'"

    # B-3b: taxid whitelist + raw_metadata substring fallback
    rm = raw_metadata or ""
    clean_taxids: list[int] = []
    for tid in parsed.get("organism_taxids", []):
        if tid in TAXID_WHITELIST or str(tid) in rm:
            clean_taxids.append(tid)
        else:
            log.warning("dropping unknown taxid %s (not in whitelist nor raw_metadata)", tid)
    parsed["organism_taxids"] = clean_taxids

    # B-3c: subject_id_hint pattern must compile + match its example + example must be a sample title
    hint = parsed.get("subject_id_hint", {})
    if hint.get("applies"):
        pat, ex = hint.get("pattern"), hint.get("example")
        ok = bool(pat and ex and ex in sample_titles)
        if ok:
            try:
                m = re.search(pat, ex)
                ok = bool(m and "subject" in (m.groupdict() or {}))
            except re.error:
                ok = False
        if not ok:
            hint["applies"], hint["pattern"], hint["example"] = False, None, None

    # B-3d: non-unknown design_type requires >=1 group
    cd = parsed.get("cohort_design", {})
    if cd.get("design_type") != "unknown" and not cd.get("groups"):
        cd["design_type"] = "unknown"

    return True, ""


async def llm_extract_sol4(
    client: httpx.AsyncClient, prompt: str, sample_titles: list[str], raw_metadata: str,
) -> dict | None:
    """Stage A→D: generate → validate → retry once → skip.

    Note: _ollama_generate raises InfrastructureError on infrastructure-exhausted; we
    deliberately do NOT catch it here so it propagates to the harvest loop where the
    circuit breaker lives.
    """
    parsed = await _ollama_generate(client, prompt, temperature=0.1)
    if parsed is not None:
        ok, err = _semantic_validate(parsed, sample_titles, raw_metadata)
        if ok:
            return parsed
        retry_msg = err
    else:
        retry_msg = "json parse error"

    # Stage C: retry once, temperature 0
    retry_prompt = (
        prompt + f"\n\nYOUR PREVIOUS RESPONSE FAILED VALIDATION. ERROR: {retry_msg[:200]}. "
        "Re-emit the JSON object correctly. Output ONLY the JSON object, nothing else."
    )
    parsed = await _ollama_generate(client, retry_prompt, temperature=0.0)
    if parsed is None:
        return None
    ok, err = _semantic_validate(parsed, sample_titles, raw_metadata)
    if not ok:
        log.warning("sol4 extract hard-skip after retry: %s", err)
        return None
    return parsed


# ─────────── DB writes (merge policy: never shrink) ───────────
async def _fetch_sample_titles(pg: asyncpg.Connection, dataset_id) -> list[str]:
    rows = await pg.fetch(SAMPLE_TITLES_SQL, dataset_id)
    titles: list[str] = []
    for r in rows:
        attrs = r["raw_attributes"] or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                attrs = {}
        # source_sample_id is most stable; sample 'title' may live in raw_attributes
        t = (attrs.get("title") or attrs.get("Sample_title") or r["source_sample_id"] or "").strip()
        if t:
            titles.append(t)
    return titles


def _merge_strict_superset(old: list[str] | None, new: list[str]) -> tuple[list[str], bool]:
    """Return (merged, did_change). Never shrink: only overwrite if old empty OR new ⊇ old."""
    old_set = set(old or [])
    new_set = set(new or [])
    if not old_set:
        return new, bool(new)
    if old_set.issubset(new_set) and new_set != old_set:
        return list(new_set), True
    return list(old_set), False


UPDATE_DATASET_SQL = """
UPDATE datasets
   SET tissue_ids         = $2::text[],
       cell_type_ids      = $3::text[],
       disease_ids        = $4::text[],
       cohort_design      = $5::jsonb,
       raw_metadata       = COALESCE(raw_metadata, '{}'::jsonb) || $6::jsonb,
       extraction_version = $7,
       extraction_lineage_id = $8,
       build_stage = $9
 WHERE id = $1
"""

INSERT_DATASET_SOURCE_SQL = """
INSERT INTO dataset_sources (dataset_id, source_db, source_id, raw_url, is_primary, linked_via)
VALUES ($1, $2, $3, $4, false, $5)
ON CONFLICT (dataset_id, source_db, source_id) DO NOTHING
"""


async def apply_extraction(
    pg: asyncpg.Connection, row: dict, extract: dict, *, dry_run: bool,
) -> bool:
    """Write the sol4 extraction to datasets + dataset_sources. Returns True if changed."""
    # OntologyMapper for label→CURIE (lazy import — dry-run never touches this).
    from src.extractors.llm_client import OllamaClient  # noqa: F401  # implicit env-check
    from src.ontology.mapper import OntologyMapper

    # PARALLEL OLS4 (2026-06-08): label lookups are independent;
    # the 3 vocabularies are independent → run concurrently. ~3x speedup on the bottleneck
    # (Sol 4 per-dataset ~18s split: gemma4 ~5s + OLS4 ~10s + DB ~3s).
    # Bonus: also fan out individual labels inside via _lookup_labels_parallel below.
    sem = asyncio.Semaphore(8)  # cap OLS4 concurrency (be polite)

    async def _lookup_labels_parallel(mapper, labels: list[str], ontology: str) -> list[str]:
        async def one(t: str):
            async with sem:
                return await mapper.lookup(t, ontology)
        if not labels:
            return []
        ms = await asyncio.gather(*[one(t) for t in labels], return_exceptions=False)
        seen: dict[str, Any] = {}
        for m in ms:
            if m is not None:
                seen[m.curie] = m
        # Bug fix (2026-06-08): return List[str] (CURIEs), not List[Match].
        # Downstream _merge_strict_superset + UPDATE ... $2::text[] expects strings.
        return list(seen.keys())

    async with OntologyMapper() as mapper:
        new_tissue_ids, new_cell_ids, new_disease_ids = await asyncio.gather(
            _lookup_labels_parallel(mapper, extract.get("tissues") or [],    "uberon"),
            _lookup_labels_parallel(mapper, extract.get("cell_types") or [], "cl"),
            _lookup_labels_parallel(mapper, extract.get("diseases") or [],   "mondo"),
        )

    merged_tissue,  t_changed = _merge_strict_superset(row.get("tissue_ids"),    new_tissue_ids)
    merged_cell,    c_changed = _merge_strict_superset(row.get("cell_type_ids"), new_cell_ids)
    merged_disease, d_changed = _merge_strict_superset(row.get("disease_ids"),   new_disease_ids)

    cohort_design = extract.get("cohort_design") or {"design_type": "unknown", "groups": []}
    cohort_design["cohort_design_version"] = EXTRACTION_VERSION

    raw_meta_patch = {
        "sol4_compound_flags": extract.get("compound_flags") or {},
        "sol4_subject_id_pattern": (
            extract.get("subject_id_hint", {}).get("pattern")
            if extract.get("subject_id_hint", {}).get("applies") else None
        ),
        "sol4_notes": (extract.get("notes") or "")[:300],
        "sol4_extracted_at": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        return any([t_changed, c_changed, d_changed])

    await pg.execute(
        UPDATE_DATASET_SQL,
        row["id"],
        merged_tissue,
        merged_cell,
        merged_disease,
        json.dumps(cohort_design),
        json.dumps(raw_meta_patch),
        EXTRACTION_VERSION,
        composite_lineage_id(SOL4_STAGE_LINEAGE_ID, row.get("extraction_lineage_id")),
        BUILD_STAGE_MODEL_ENRICHED,
    )
    await pg.execute(
        INSERT_DATASET_SOURCE_SQL,
        row["id"], row["source_db"], row["source_id"],
        f"sol4-retag://{row['source_db']}/{row['source_id']}",
        LINKED_VIA_MARKER,
    )
    return any([t_changed, c_changed, d_changed])


# ─────────── Dry-run path ───────────
async def _dry_run(limit: int) -> int:
    log.info("DRY-RUN: counting candidates + showing 3 samples (no LLM, no DB write)")
    pg = await asyncpg.connect(_pg_dsn())
    try:
        total_row = await pg.fetchrow(CANDIDATE_COUNT_SQL)
        total = int(total_row["n"])
        sample = await pg.fetch(PRIORITY_CANDIDATE_SQL, 0, min(3, limit))
    finally:
        await pg.close()

    print(f"candidate_total: {total}")
    print(f"limit_applied:   {limit}")
    print(f"effective_n:     {min(total, limit)}")
    print("sample_top_3:")
    for r in sample:
        print(f"  - id={r['id']} {r['source_db']}/{r['source_id']} "
              f"n_samples={r['n_samples']} weakness_score={r['weakness_score']}  "
              f"title={(r['title'] or '')[:80]!r}")
    print(f"checkpoint_path: {CHECKPOINT_PATH}")
    print(f"log_path:        {LOG_PATH}")
    print(f"ollama_url:      {OLLAMA_URL}")
    print(f"ollama_model:    {OLLAMA_MODEL}")
    return 0


# ─────────── Main harvest loop ───────────
async def harvest(*, limit: int, resume: bool, batch_size: int) -> int:
    # Redis source_lock — reuse existing helper.
    from src.scheduling.watermark import set_watermark, source_lock

    state = _load_checkpoint() if resume else {
        "offset": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0,
        "started_at": time.time(),
    }
    # Ensure circuit-breaker keys exist for older checkpoint files.
    state.setdefault("consecutive_connect_errors", 0)
    state.setdefault("circuit_breaker_open", False)

    if state.get("circuit_breaker_open"):
        log.critical(
            "REFUSING TO START: checkpoint shows circuit_breaker_open=True at offset=%d. "
            "Reset the flag manually (edit %s) after confirming ollama 11435 is healthy.",
            state["offset"], CHECKPOINT_PATH,
        )
        return 3

    log.info("sol4 retag starting: offset=%d updated=%d skipped=%d errors=%d limit=%d batch=%d cb_threshold=%d",
             state["offset"], state["updated"], state["skipped"], state["errors"], limit, batch_size, CB_THRESHOLD)

    async with source_lock("SOL4-RETAG", ttl_s=LOCK_TTL_S) as acquired:
        if not acquired:
            log.error("could not acquire SOL4-RETAG lock — another worker already running")
            return 2

        pg = await asyncpg.connect(_pg_dsn())
        http = httpx.AsyncClient(timeout=OLLAMA_TIMEOUT)
        try:
            total_row = await pg.fetchrow(CANDIDATE_COUNT_SQL)
            total = int(total_row["n"])
            log.info("candidate pool: %d (will process up to %d)", total, limit)

            offset = state["offset"]
            remaining = max(0, limit - (state["updated"] + state["skipped"] + state["errors"]))
            page_size = max(batch_size * 25, 100)

            while remaining > 0 and not _should_stop:
                rows = await pg.fetch(
                    PRIORITY_CANDIDATE_SQL, offset, min(page_size, remaining)
                )
                if not rows:
                    log.info("no more candidates at offset=%d", offset)
                    break

                for r in rows:
                    if _should_stop:
                        break
                    row = dict(r)
                    sample_titles = await _fetch_sample_titles(pg, row["id"])
                    raw_meta_text = (
                        json.dumps(row["raw_metadata"])
                        if isinstance(row["raw_metadata"], (dict, list))
                        else (row["raw_metadata"] or "")
                    )
                    prompt = _build_prompt(
                        title=row.get("title") or "",
                        abstract=row.get("abstract") or "",
                        raw_metadata=raw_meta_text,
                        sample_titles=sample_titles,
                    )
                    try:
                        extract = await llm_extract_sol4(http, prompt, sample_titles, raw_meta_text)
                    except InfrastructureError as ie:
                        state["errors"] += 1
                        state["consecutive_connect_errors"] += 1
                        log.warning(
                            "infrastructure failure on dataset_id=%s: %s (consecutive=%d/%d)",
                            row.get("id"), ie,
                            state["consecutive_connect_errors"], CB_THRESHOLD,
                        )
                        if state["consecutive_connect_errors"] >= CB_THRESHOLD:
                            state["circuit_breaker_open"] = True
                            state["offset"] = offset  # already-processed dataset count is final
                            _save_checkpoint(state)
                            log.critical(
                                "CIRCUIT BREAKER OPEN: %d consecutive ollama infrastructure failures "
                                "at offset=%d. Halting. Watchdog must restart ollama 11435 and "
                                "reset circuit_breaker_open=False in %s before resuming.",
                                state["consecutive_connect_errors"], offset, CHECKPOINT_PATH,
                            )
                            return 1
                        offset += 1
                        state["offset"] = offset
                        remaining -= 1
                        continue
                    if extract is None:
                        # Model-output failure (json decode / validation). NOT infrastructure.
                        state["errors"] += 1
                        state["consecutive_connect_errors"] = 0
                    else:
                        try:
                            changed = await apply_extraction(pg, row, extract, dry_run=False)
                            if changed:
                                state["updated"] += 1
                            else:
                                state["skipped"] += 1
                            state["consecutive_connect_errors"] = 0
                        except Exception as e:
                            log.warning("apply_extraction failed for %s: %s",
                                        row.get("source_id"), e)
                            state["errors"] += 1
                            # DB write failure is not ollama infra — don't trip CB.
                            state["consecutive_connect_errors"] = 0

                    offset += 1
                    state["offset"] = offset
                    remaining -= 1

                    processed = state["updated"] + state["skipped"] + state["errors"]
                    if processed > 0 and processed % LOG_EVERY == 0:
                        elapsed = time.time() - state["started_at"]
                        rate = processed / elapsed if elapsed > 0 else 0.0
                        log.info("progress: updated=%d skipped=%d errors=%d  (%.2f/s, offset=%d)",
                                 state["updated"], state["skipped"], state["errors"], rate, offset)
                        _save_checkpoint(state)

                _save_checkpoint(state)

            await set_watermark("SOL4-RETAG", when=datetime.now(timezone.utc))
            log.info("=" * 60)
            if _should_stop:
                log.info("PAUSED at offset=%d", state["offset"])
            else:
                log.info("DONE — updated=%d skipped=%d errors=%d",
                         state["updated"], state["skipped"], state["errors"])
            return 0
        finally:
            await http.aclose()
            await pg.close()
            _save_checkpoint(state)
            REPORT_PATH.write_text(json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "extraction_version": EXTRACTION_VERSION,
                **state,
            }, indent=2))


# ════════════════════════════════════════════════════════════════════════════
# AUTO-MODE: self-healing 점진 재태깅 (2026-06-12)
# ────────────────────────────────────────────────────────────────────────────
# 목적: 매일 새벽 Celery beat 가 호출 → weakness_score 높은 부실분만 N건씩 점진
#   보정. 기존 1회성 harvest() 는 손대지 않고 전부 별도 함수로 분리(격리).
#
# 안전 설계 (사용자 요구: "기존 정보 절대 안 해침 + 재태깅 무조건 좋은 거 아님"):
#   - never-shrink: tissue/cell/disease 는 _merge_strict_superset 그대로 (확대만).
#   - cohort 보호: 기존 cohort_design 이 실제값(non-unknown)이면 절대 덮어쓰지 않음
#     (1회성 harvest() 는 cohort 를 무조건 덮어썼지만, 자동 모드는 빈칸일 때만 채움).
#   - OLS4 exact-match 게이트(mapper.lookup) → 근거 없는 라벨은 None → 무시(hallucination 차단).
#   - 5 게이트: ①신선도(version) ②풍부분 제외 ③최소근거 ④커서리스(seen-id) ⑤드리프트 가드.
#   - shadow 모드: LLM/온톨로지/merge 까지 다 돌리되 DB write 0, diff 만 로그(도입 첫 3-5일 검증용).
# ════════════════════════════════════════════════════════════════════════════

AUTO_STATE_PATH = Path("/tmp/genofinder-sol4-auto-state.json")

# 드리프트 가드: updated 가 충분히 쌓였는데 평균 new-CURIE/updated 가 비정상이면 모델
# 이상으로 보고 중단. shadow 모드가 1차 안전망이라 cap 은 넉넉히(false-positive 방지).
AUTO_DRIFT_MIN_SAMPLE = int(os.environ.get("SOL4_AUTO_DRIFT_MIN_SAMPLE", "50"))
AUTO_DRIFT_AVG_CURIE_CAP = float(os.environ.get("SOL4_AUTO_DRIFT_AVG_CURIE_CAP", "8.0"))

# 후보 SQL: weakness_score 확장 + 게이트①②③. 게이트④(seen-id)·페이지는 파라미터로.
#   $1 = sol4 EXTRACTION_VERSION (신선도 게이트),  $2 = 이번 런에서 이미 본 id[] (uuid[]),
#   $3 = 이번 fetch 상한.
AUTO_PRIORITY_CANDIDATE_SQL = """
WITH scored AS (
  SELECT
    d.id, d.source_db, d.source_id, d.title, d.abstract, d.n_samples,
    d.raw_metadata, d.tissue_ids, d.cell_type_ids, d.disease_ids, d.cohort_design,
    d.extraction_lineage_id,
    (
        (CASE WHEN COALESCE(array_length(d.tissue_ids, 1), 0)    = 0 THEN 1 ELSE 0 END)
      + (CASE WHEN COALESCE(array_length(d.cell_type_ids, 1), 0) = 0 THEN 1 ELSE 0 END)
      + (CASE WHEN COALESCE(array_length(d.disease_ids, 1), 0)   = 0 THEN 1 ELSE 0 END)
      + (CASE WHEN (d.cohort_design IS NULL
                    OR d.cohort_design->>'design_type' IS NULL
                    OR d.cohort_design->>'design_type' = 'unknown') THEN 1 ELSE 0 END)
      + (CASE WHEN d.extraction_version IS NULL
                   OR d.extraction_version LIKE 'v0-%'
                   OR d.extraction_version ILIKE '%phi4%' THEN 2 ELSE 0 END)
      + (CASE WHEN d.n_samples >= 4
                   AND (d.cohort_design IS NULL
                        OR d.cohort_design->>'design_type' = 'unknown') THEN 2 ELSE 0 END)
      + (CASE WHEN (d.title ILIKE '%paired%' OR d.title ILIKE '%matched%'
                    OR d.title ILIKE '%longitudinal%'
                    OR d.abstract ILIKE '%paired%' OR d.abstract ILIKE '%matched%'
                    OR d.abstract ILIKE '%longitudinal%')
                   AND (d.cohort_design IS NULL
                        OR d.cohort_design->>'design_type' = 'unknown') THEN 2 ELSE 0 END)
    ) AS weakness_score
  FROM datasets d
  WHERE
    -- 게이트①(신선도): 이미 현재 sol4 버전으로 처리된 건 자동 제외 → 커서리스
    d.extraction_version IS DISTINCT FROM $1
    -- 게이트②(풍부분 제외): tissue+disease+cohort 다 채워진 건 건드리지 않음
    AND NOT (
      COALESCE(array_length(d.tissue_ids, 1), 0)  >= 1
      AND COALESCE(array_length(d.disease_ids, 1), 0) >= 1
      AND d.cohort_design IS NOT NULL
      AND d.cohort_design->>'design_type' IS NOT NULL
      AND d.cohort_design->>'design_type' <> 'unknown'
    )
    -- 게이트③(최소근거, SQL 1차): 진짜 초록이 있거나 샘플 4개 이상
    AND (
      (d.abstract IS NOT NULL AND length(trim(d.abstract)) >= 40)
      OR d.n_samples >= 4
    )
    -- 게이트④(커서리스): 이번 런에서 이미 시도한 id 제외(에러 poison row 무한루프 방지)
    AND d.id <> ALL($2::uuid[])
)
SELECT * FROM scored
WHERE weakness_score > 0
ORDER BY weakness_score DESC, n_samples DESC NULLS LAST, id
LIMIT $3
"""

AUTO_CANDIDATE_COUNT_SQL = """
SELECT count(*) AS n
FROM datasets d
WHERE d.extraction_version IS DISTINCT FROM $1
  AND NOT (
    COALESCE(array_length(d.tissue_ids, 1), 0)  >= 1
    AND COALESCE(array_length(d.disease_ids, 1), 0) >= 1
    AND d.cohort_design IS NOT NULL
    AND d.cohort_design->>'design_type' IS NOT NULL
    AND d.cohort_design->>'design_type' <> 'unknown'
  )
  AND (
    (d.abstract IS NOT NULL AND length(trim(d.abstract)) >= 40)
    OR d.n_samples >= 4
  )
"""

# 최소근거 미달(초록 없음 + 샘플 제목 빈약) 건을 LLM 없이 버전만 찍어 후보에서 탈락시킴
# (다음 밤에 같은 부실 row 가 weakness 상위로 다시 올라와 큐를 막는 것 방지). 데이터는
# domain metadata 값은 건드리지 않지만 version을 바꾸므로 기존 lineage 적격성은 무효화한다.
STAMP_VERSION_ONLY_SQL = """
UPDATE datasets
   SET extraction_version = $2,
       extraction_lineage_id = NULL,
       build_stage = NULL
 WHERE id = $1
"""

# 실제 cohort_design 이 이미 있는 dataset 용 — cohort_design 을 SET 에서 제외하여 원본을
# 절대 건드리지 않음(파싱 가능 여부와 무관, P4 by construction). $5=raw_meta_patch, $6=version.
UPDATE_DATASET_NO_COHORT_SQL = """
UPDATE datasets
   SET tissue_ids         = $2::text[],
       cell_type_ids      = $3::text[],
       disease_ids        = $4::text[],
       raw_metadata       = COALESCE(raw_metadata, '{}'::jsonb) || $5::jsonb,
       extraction_version = $6,
       extraction_lineage_id = $7,
       build_stage = $8
 WHERE id = $1
"""


def _save_auto_state(state: dict[str, Any]) -> None:
    try:
        AUTO_STATE_PATH.write_text(json.dumps(
            {**state, "saved_at": datetime.now(timezone.utc).isoformat()},
            indent=2, default=str,
        ))
    except Exception as e:  # state 저장 실패는 치명적이지 않음
        log.warning("auto-state save failed: %s", e)


def _cohort_design_type(cohort: Any) -> str | None:
    """asyncpg 가 JSONB 를 str 로 줄 수도 dict 로 줄 수도 있어 양쪽 처리."""
    if isinstance(cohort, dict):
        return cohort.get("design_type")
    if isinstance(cohort, str):
        try:
            return (json.loads(cohort) or {}).get("design_type")
        except Exception:
            return None
    return None


async def apply_extraction_auto(
    pg: asyncpg.Connection, row: dict, extract: dict, *, shadow: bool,
) -> tuple[bool, int]:
    """auto-mode write. Returns (did_change, n_new_curies).

    1회성 apply_extraction 과의 핵심 차이:
      - cohort_design 은 기존이 빈칸/unknown 일 때만 채움(실제값은 절대 덮어쓰지 않음).
      - shadow=True 면 모든 계산은 하되 DB write 0, diff 만 로그.
    tissue/cell/disease 는 동일하게 never-shrink(_merge_strict_superset).
    """
    from src.extractors.llm_client import OllamaClient  # noqa: F401  # implicit env-check
    from src.ontology.mapper import OntologyMapper

    sem = asyncio.Semaphore(8)

    async def _lookup_labels_parallel(mapper, labels: list[str], ontology: str) -> list[str]:
        async def one(t: str):
            async with sem:
                return await mapper.lookup(t, ontology)
        if not labels:
            return []
        ms = await asyncio.gather(*[one(t) for t in labels])
        seen: dict[str, Any] = {}
        for m in ms:
            if m is not None:
                seen[m.curie] = m
        return list(seen.keys())

    async with OntologyMapper() as mapper:
        new_tissue_ids, new_cell_ids, new_disease_ids = await asyncio.gather(
            _lookup_labels_parallel(mapper, extract.get("tissues") or [],    "uberon"),
            _lookup_labels_parallel(mapper, extract.get("cell_types") or [], "cl"),
            _lookup_labels_parallel(mapper, extract.get("diseases") or [],   "mondo"),
        )

    merged_tissue,  t_changed = _merge_strict_superset(row.get("tissue_ids"),    new_tissue_ids)
    merged_cell,    c_changed = _merge_strict_superset(row.get("cell_type_ids"), new_cell_ids)
    merged_disease, d_changed = _merge_strict_superset(row.get("disease_ids"),   new_disease_ids)

    def _added(old: list[str] | None, merged: list[str]) -> int:
        return len(set(merged) - set(old or []))

    n_new = (_added(row.get("tissue_ids"), merged_tissue)
             + _added(row.get("cell_type_ids"), merged_cell)
             + _added(row.get("disease_ids"), merged_disease))

    # cohort: 기존이 "빈칸/unknown" 일 때만 새 값으로 채움. 실제 design 이 있거나, 내용은
    # 있는데 구조를 못 읽는(레거시/비정형) 경우엔 보존 쪽으로 분기 → cohort 컬럼을 UPDATE
    # SET 에서 제외하여 원본을 절대 손대지 않음(파싱 가능 여부와 무관, P4 by construction).
    old_cohort = row.get("cohort_design")
    old_dt = _cohort_design_type(old_cohort)
    old_present = (
        (isinstance(old_cohort, dict) and bool(old_cohort))
        or (isinstance(old_cohort, str) and bool(old_cohort.strip()))
    )
    # 존재하지만 design_type 을 못 읽으면(old_dt is None and old_present) 빈칸으로 보지 않음.
    cohort_blank = (old_dt in (None, "unknown")) and not (old_dt is None and old_present)
    new_cohort = extract.get("cohort_design") or {"design_type": "unknown", "groups": []}
    new_dt = new_cohort.get("design_type")
    cohort_changed = cohort_blank and new_dt not in (None, "unknown")

    changed = any([t_changed, c_changed, d_changed, cohort_changed])

    if shadow:
        log.info(
            "auto-retag SHADOW id=%s %s/%s | +tissue=%s +cell=%s +disease=%s "
            "cohort:%s%s | would_change=%s",
            row.get("id"), row.get("source_db"), row.get("source_id"),
            sorted(set(merged_tissue) - set(row.get("tissue_ids") or [])),
            sorted(set(merged_cell) - set(row.get("cell_type_ids") or [])),
            sorted(set(merged_disease) - set(row.get("disease_ids") or [])),
            old_dt, (f"→{new_dt}" if cohort_changed else "(보존)"),
            changed,
        )
        return changed, n_new

    raw_meta_patch = {
        "sol4_compound_flags": extract.get("compound_flags") or {},
        "sol4_subject_id_pattern": (
            extract.get("subject_id_hint", {}).get("pattern")
            if extract.get("subject_id_hint", {}).get("applies") else None
        ),
        "sol4_notes": (extract.get("notes") or "")[:300],
        "sol4_auto_extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    if cohort_blank:
        cohort_to_write = dict(new_cohort)
        cohort_to_write["cohort_design_version"] = EXTRACTION_VERSION
        await pg.execute(
            UPDATE_DATASET_SQL,
            row["id"], merged_tissue, merged_cell, merged_disease,
            json.dumps(cohort_to_write), json.dumps(raw_meta_patch), EXTRACTION_VERSION,
            composite_lineage_id(SOL4_STAGE_LINEAGE_ID, row.get("extraction_lineage_id")),
            BUILD_STAGE_MODEL_ENRICHED,
        )
    else:
        # 실제(또는 비정형) cohort 보존 — cohort_design 컬럼은 UPDATE 대상에서 제외.
        await pg.execute(
            UPDATE_DATASET_NO_COHORT_SQL,
            row["id"], merged_tissue, merged_cell, merged_disease,
            json.dumps(raw_meta_patch), EXTRACTION_VERSION,
            composite_lineage_id(SOL4_STAGE_LINEAGE_ID, row.get("extraction_lineage_id")),
            BUILD_STAGE_MODEL_ENRICHED,
        )
    await pg.execute(
        INSERT_DATASET_SOURCE_SQL,
        row["id"], row["source_db"], row["source_id"],
        f"sol4-retag://{row['source_db']}/{row['source_id']}", LINKED_VIA_MARKER,
    )
    return changed, n_new


async def harvest_auto(
    *,
    daily_cap: int,
    shadow: bool,
    batch_size: int = 1,
    metrics_jsonl: Path | None = None,
) -> dict[str, Any]:
    """무인 점진 재태깅(self-healing). 매일 새벽 Celery beat → 부실분 N건 보정.

    Returns: state dict + exit_code (0=정상, 1=circuit_breaker, 2=locked, 4=drift_guard).
    lock 은 "SOL4-RETAG" 공유 → 1회성 Sol4 런 / 직전 밤 런과 자동 상호배제(GPU 경합 방지).
    """
    from src.scheduling.watermark import set_watermark, source_lock

    _install_signal_handlers()  # idempotent

    sol4_version = EXTRACTION_VERSION
    started = time.time()
    state: dict[str, Any] = {
        "mode": "shadow" if shadow else "commit",
        "updated": 0, "skipped": 0, "errors": 0, "low_evidence": 0,
        "new_curies_total": 0, "consecutive_connect_errors": 0,
        "started_at": started,
    }
    seen_ids: list = []

    def _metric(payload: dict[str, Any]) -> None:
        """Append privacy-safe operational timings when explicitly requested."""
        if metrics_jsonl is None:
            return
        metrics_jsonl.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": state["mode"],
            "extraction_version": sol4_version,
            "model": OLLAMA_MODEL,
            **payload,
        }
        with metrics_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _processed() -> int:
        return state["updated"] + state["skipped"] + state["errors"] + state["low_evidence"]

    async with source_lock("SOL4-RETAG", ttl_s=LOCK_TTL_S) as acquired:
        if not acquired:
            log.warning("auto-retag skipped — SOL4-RETAG lock held "
                        "(1회성 Sol4 런 또는 직전 밤 런 진행 중)")
            return {**state, "exit_code": 2, "reason": "locked"}

        pg = await asyncpg.connect(_pg_dsn())
        http = httpx.AsyncClient(timeout=OLLAMA_TIMEOUT)
        try:
            count_started = time.perf_counter()
            cnt = await pg.fetchrow(AUTO_CANDIDATE_COUNT_SQL, sol4_version)
            candidate_count_ms = (time.perf_counter() - count_started) * 1000
            pool = int(cnt["n"]) if cnt else 0
            state["candidate_pool"] = pool
            state["candidate_count_ms"] = candidate_count_ms
            _metric({
                "event": "candidate_count",
                "elapsed_ms": candidate_count_ms,
                "candidate_pool": pool,
            })
            log.info("auto-retag START mode=%s daily_cap=%d candidate_pool~%d shadow=%s",
                     state["mode"], daily_cap, pool, shadow)

            page_size = max(batch_size * 25, 50)
            while _processed() < daily_cap and not _should_stop:
                remaining = daily_cap - _processed()
                select_started = time.perf_counter()
                rows = await pg.fetch(
                    AUTO_PRIORITY_CANDIDATE_SQL, sol4_version, seen_ids,
                    min(page_size, remaining),
                )
                _metric({
                    "event": "candidate_select",
                    "elapsed_ms": (time.perf_counter() - select_started) * 1000,
                    "requested": min(page_size, remaining),
                    "returned": len(rows),
                })
                if not rows:
                    log.info("auto-retag: candidate pool drained (남은 부실분 없음)")
                    break

                for r in rows:
                    if _should_stop:
                        break
                    row = dict(r)
                    seen_ids.append(row["id"])
                    row_started = time.perf_counter()
                    row_metric: dict[str, Any] = {
                        "event": "dataset",
                        "dataset_id": str(row["id"]),
                        "source_db": row["source_db"],
                        "source_id": row["source_id"],
                        "weakness_score": row["weakness_score"],
                        "n_samples": row["n_samples"],
                    }

                    sample_started = time.perf_counter()
                    sample_titles = await _fetch_sample_titles(pg, row["id"])
                    row_metric["sample_fetch_ms"] = (
                        time.perf_counter() - sample_started
                    ) * 1000
                    row_metric["sample_titles_n"] = len(sample_titles)
                    abstract = (row.get("abstract") or "").strip()
                    titles_chars = sum(len(t) for t in sample_titles)
                    # 게이트③(최소근거, 런타임 2차): 초록 없음 + 샘플 제목 빈약 → 저신뢰 스킵
                    if not abstract and titles_chars < 30:
                        state["low_evidence"] += 1
                        state["consecutive_connect_errors"] = 0
                        if not shadow:
                            await pg.execute(STAMP_VERSION_ONLY_SQL, row["id"], sol4_version)
                        log.info("auto-retag low-evidence skip id=%s (초록X + 샘플제목 빈약)",
                                 row["id"])
                        row_metric.update({
                            "outcome": "low_evidence",
                            "elapsed_ms": (time.perf_counter() - row_started) * 1000,
                        })
                        _metric(row_metric)
                        continue

                    raw_meta_text = (
                        json.dumps(row["raw_metadata"])
                        if isinstance(row["raw_metadata"], (dict, list))
                        else (row["raw_metadata"] or "")
                    )
                    prompt = _build_prompt(
                        title=row.get("title") or "", abstract=row.get("abstract") or "",
                        raw_metadata=raw_meta_text, sample_titles=sample_titles,
                    )
                    llm_started = time.perf_counter()
                    try:
                        extract = await llm_extract_sol4(http, prompt, sample_titles, raw_meta_text)
                    except InfrastructureError as ie:
                        row_metric.update({
                            "outcome": "infrastructure_error",
                            "llm_ms": (time.perf_counter() - llm_started) * 1000,
                            "elapsed_ms": (time.perf_counter() - row_started) * 1000,
                            "error_type": type(ie).__name__,
                        })
                        _metric(row_metric)
                        state["errors"] += 1
                        state["consecutive_connect_errors"] += 1
                        log.warning("auto-retag infra failure id=%s: %s (consecutive=%d/%d)",
                                    row["id"], ie, state["consecutive_connect_errors"], CB_THRESHOLD)
                        if state["consecutive_connect_errors"] >= CB_THRESHOLD:
                            log.critical("auto-retag CIRCUIT BREAKER OPEN: %d consecutive infra "
                                         "failures. Halting.", state["consecutive_connect_errors"])
                            _save_auto_state(state)
                            return {**state, "exit_code": 1, "reason": "circuit_breaker"}
                        continue
                    if extract is None:
                        row_metric.update({
                            "outcome": "model_or_validation_error",
                            "llm_ms": (time.perf_counter() - llm_started) * 1000,
                            "elapsed_ms": (time.perf_counter() - row_started) * 1000,
                        })
                        _metric(row_metric)
                        state["errors"] += 1
                        state["consecutive_connect_errors"] = 0
                        continue

                    row_metric["llm_ms"] = (time.perf_counter() - llm_started) * 1000
                    normalize_started = time.perf_counter()
                    try:
                        changed, n_new = await apply_extraction_auto(pg, row, extract, shadow=shadow)
                        row_metric.update({
                            "outcome": "updated" if changed else "no_change",
                            "normalization_merge_ms": (
                                time.perf_counter() - normalize_started
                            ) * 1000,
                            "new_curies": n_new,
                            "changed": changed,
                            "elapsed_ms": (time.perf_counter() - row_started) * 1000,
                        })
                        _metric(row_metric)
                        state["new_curies_total"] += n_new
                        if changed:
                            state["updated"] += 1
                        else:
                            state["skipped"] += 1
                        state["consecutive_connect_errors"] = 0
                    except Exception as e:
                        row_metric.update({
                            "outcome": "normalization_or_apply_error",
                            "normalization_merge_ms": (
                                time.perf_counter() - normalize_started
                            ) * 1000,
                            "elapsed_ms": (time.perf_counter() - row_started) * 1000,
                            "error_type": type(e).__name__,
                        })
                        _metric(row_metric)
                        log.warning("auto-retag apply failed id=%s: %s", row["id"], e)
                        state["errors"] += 1
                        state["consecutive_connect_errors"] = 0

                    # 게이트⑤(드리프트 가드): 평균 new-CURIE/updated 비정상이면 중단
                    if state["updated"] >= AUTO_DRIFT_MIN_SAMPLE:
                        avg = state["new_curies_total"] / max(1, state["updated"])
                        if avg > AUTO_DRIFT_AVG_CURIE_CAP:
                            log.critical("auto-retag DRIFT GUARD: avg new-CURIE/updated=%.2f > %.2f "
                                         "after %d updates → 모델 드리프트 의심, 중단.",
                                         avg, AUTO_DRIFT_AVG_CURIE_CAP, state["updated"])
                            _save_auto_state(state)
                            return {**state, "exit_code": 4, "reason": "drift_guard"}

                    if _processed() % LOG_EVERY == 0:
                        elapsed = time.time() - started
                        rate = _processed() / elapsed if elapsed > 0 else 0.0
                        log.info("auto-retag progress: updated=%d skipped=%d errors=%d low_ev=%d "
                                 "(%.3f/s)", state["updated"], state["skipped"], state["errors"],
                                 state["low_evidence"], rate)
                        _save_auto_state(state)

            if not shadow:
                await set_watermark("SOL4-AUTO-RETAG", when=datetime.now(timezone.utc))
            state["elapsed_seconds"] = time.time() - started
            state["processed"] = _processed()
            state["throughput_per_hour"] = (
                _processed() / state["elapsed_seconds"] * 3600
                if state["elapsed_seconds"] > 0 else 0.0
            )
            _metric({"event": "run_summary", **state})
            log.info("auto-retag DONE mode=%s updated=%d skipped=%d errors=%d low_ev=%d new_curies=%d",
                     state["mode"], state["updated"], state["skipped"], state["errors"],
                     state["low_evidence"], state["new_curies_total"])
            return {**state, "exit_code": 0, "reason": "ok"}
        finally:
            await http.aclose()
            await pg.close()
            _save_auto_state(state)


# ─────────── CLI entry ───────────
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print candidate count + 3 samples, no LLM, no DB write")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"max datasets to process (default {DEFAULT_LIMIT})")
    parser.add_argument("--resume", action="store_true",
                        help="resume from /tmp/genofinder-sol4-checkpoint.json")
    parser.add_argument("--batch-size", type=int, default=1,
                        help="serial batch unit (default 1 — gemma4:31b is GPU-heavy)")
    parser.add_argument("--auto-mode", action="store_true",
                        help="self-healing 점진 재태깅 (커서리스 + 5 게이트). 1회성 모드와 별개.")
    parser.add_argument("--commit", action="store_true",
                        help="auto-mode 에서 실제 DB write. 미지정 시 shadow(diff 만 로그) 기본.")
    parser.add_argument("--daily-cap", type=int, default=500,
                        help="auto-mode 1회 처리 상한 (default 500)")
    parser.add_argument("--metrics-jsonl", type=Path,
                        help="append privacy-safe per-stage auto-mode timings to this JSONL")
    args = parser.parse_args()

    if args.dry_run:
        return asyncio.run(_dry_run(limit=args.limit))
    if args.auto_mode:
        shadow = not args.commit  # 기본 shadow — 검증 끝나고 --commit 으로 실제 write
        result = asyncio.run(harvest_auto(
            daily_cap=args.daily_cap, shadow=shadow, batch_size=args.batch_size,
            metrics_jsonl=args.metrics_jsonl,
        ))
        return int(result.get("exit_code", 0))
    return asyncio.run(harvest(
        limit=args.limit, resume=args.resume, batch_size=args.batch_size,
    ))


if __name__ == "__main__":
    sys.exit(main())
