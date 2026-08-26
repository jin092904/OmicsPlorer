"""Search request/response schemas. 마스터 플랜 §7.2 의 v1 사양 단순화.

ADR 0006 평가 (evaluation/ 패키지) 를 위해 `mode` + `corpus` 필드 추가 (2026-05).
production 트래픽은 기본값 (rrf_rerank, production) 그대로라 영향 없음.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class DateRange(BaseModel):
    start: date | None = None
    end: date | None = None


class SearchMode(StrEnum):
    """Retrieval ablation mode — 4-system evaluation 용.

    BM25_ONLY    OpenSearch BM25 단독
    DENSE_ONLY   Qdrant 1024d cosine 단독
    RRF          BM25 + Dense → Reciprocal Rank Fusion (k=60). rerank 비활성.
    RRF_RERANK   RRF top-15 → Qwen3-Reranker-0.6B reorder. **production 기본 동작.**

    Safety: `mode != RRF_RERANK` 호출은 router 가 `X-Eval-Mode: 1` 헤더를 요구하여
    production 의 실수 호출을 차단 (evaluation/ 패키지만 헤더 send).
    """

    BM25_ONLY = "bm25_only"
    DENSE_ONLY = "dense_only"
    RRF = "rrf"
    RRF_RERANK = "rrf_rerank"


class SortMode(StrEnum):
    """결과 정렬 기준. 후보 retrieval(BM25/Dense/RRF/Rerank) 후 적용.

    RELEVANCE       기본 — 모델 점수 (rerank > rrf > lexical/semantic).
    N_SAMPLES_DESC  표본 수 많은 순 (n_samples). NULL 은 후순위.
    DATE_DESC       최신순 (submission_date 내림차순). NULL 은 후순위.
    DATE_ASC        오래된 순 (submission_date 오름차순). NULL 은 후순위.
    """

    RELEVANCE = "relevance"
    N_SAMPLES_DESC = "n_samples_desc"
    DATE_DESC = "submission_date_desc"
    DATE_ASC = "submission_date_asc"


class SearchRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=2000)
    modality: list[str] | None = None  # e.g. ["scRNA-seq", "ChIP-seq"]
    organism_taxid: list[int] | None = None
    library_strategy: list[str] | None = None
    disease_ids: list[str] | None = None  # MONDO curies
    tissue_ids: list[str] | None = None  # UBERON curies
    cell_type_ids: list[str] | None = None  # CL curies
    source_db: list[str] | None = None  # 'GEO'|'SRA'|'ENA'|'GDC' 서버측 필터(빈 페이지 방지)
    # 복합 디자인 (예: urine+stool paired, human+mouse comparative) — array 필드 내 AND 필요할 때 'all'.
    # 'any' (default): 기존 OR 동작 — backwards compat. 'all': 필터된 array 가 모든 값을 포함해야 함.
    tissue_conjunction_mode: Literal["any", "all"] = "any"
    disease_conjunction_mode: Literal["any", "all"] = "any"
    modality_conjunction_mode: Literal["any", "all"] = "any"
    cell_type_conjunction_mode: Literal["any", "all"] = "any"
    organism_conjunction_mode: Literal["any", "all"] = "any"
    library_strategy_conjunction_mode: Literal["any", "all"] = "any"
    access_preference: Literal["any", "open_only"] = "open_only"
    must_have_processed_data: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    mode: SearchMode = SearchMode.RRF_RERANK  # ADR 0006 evaluation ablation
    corpus: Literal["production", "biocaddie_2016_eval"] = "production"
    sort: SortMode = SortMode.RELEVANCE  # 후보 ranking 후 재정렬
    auto_translate: bool = True  # 한국어 감지 시 자동 영어 번역 후 검색
    lang: Literal["ko", "en"] | None = None  # AI Pick reason 언어(en/ko); 검색엔 무영향


class ScoreBreakdown(BaseModel):
    semantic: float | None = None
    lexical: float | None = None
    rrf: float
    rerank: float | None = None


class SourceRef(BaseModel):
    """다중 source: GEO study 가 SRA(SRP) / ENA(ERP) 와 cross-reference 될 수 있음."""

    source_db: str  # 'GEO' | 'SRA' | 'ENA' | 'GDC' | …
    source_id: str
    raw_url: str | None = None
    is_primary: bool = False


class SearchResult(BaseModel):
    dataset_id: str
    source_db: str
    source_id: str
    title: str | None
    abstract_snippet: str | None
    score: float
    score_breakdown: ScoreBreakdown
    modality: list[str] = []
    organism_taxid: list[int]
    disease_ids: list[str] = []
    tissue_ids: list[str] = []
    cell_type_ids: list[str] = []
    library_strategy: str | None
    platform: str | None
    access_type: str
    has_processed_data: bool
    submission_date: date | None
    n_samples: int | None
    sources: list[SourceRef] = []  # 다중 source (GEO+SRA+ENA …). 없으면 primary 1건


class FacetCount(BaseModel):
    value: str
    count: int


class Facets(BaseModel):
    modality: list[FacetCount] = []
    source_db: list[FacetCount] = []
    disease_ids: list[FacetCount] = []
    tissue_ids: list[FacetCount] = []
    cell_type_ids: list[FacetCount] = []


class SearchResponse(BaseModel):
    results: list[SearchResult]
    facets: Facets = Facets()
    page: int = 1
    page_size: int = 20
    total_estimated: int
    # 실제로 페이지로 넘겨볼 수 있는 결과 수(서빙 윈도). total_estimated 는 매칭 추정치.
    servable_total: int = 0
    latency_ms: int
    query_id: str  # opaque id for feedback (later)
    # 자동 번역 발생 시 둘 다 set, UI 가 배너로 표시. 미발생 시 둘 다 None.
    original_query: str | None = None
    translated_query: str | None = None


# -- AI's Pick (project_ai_pick_feature.md) -----------------------------------
# 검색 결과 상단에 gemma4 가 엄선한 0..4 개 데이터셋 + 한 줄 이유. additive feature —
# gemma/Redis 실패 시 picks=[] 로 graceful degrade (UI 가 카드를 숨김). POST /ai-pick.


class AIPickItem(BaseModel):
    dataset_id: str
    source_db: str
    source_id: str
    title: str | None
    abstract_snippet: str | None
    score: float
    modality: list[str] = []
    n_samples: int | None
    reason: str  # gemma4 가 생성한 한국어 한 줄 추천 사유


class AIPickResponse(BaseModel):
    picks: list[AIPickItem] = []  # 0..4 items; [] → UI 가 카드 숨김
    cached: bool  # true = Redis 즉답, false = 방금 생성
    generated_at: str  # ISO8601 UTC, 예: "2026-06-12T15:30:45Z"
    model_version: str  # 예: "aipick-v1-gemma4-2026-06-12"
    query_id: str | None = None  # hybrid_search query_id passthrough (feedback)
