// 백엔드 FastAPI(/api/v1) 와의 BFF 클라이언트 + Pydantic 모델 타입 미러.
// 서버 컴포넌트에서만 호출 (CORS 회피 + lat 단축).

const API_BASE_URL =
  process.env.API_BASE_URL ?? "http://localhost:8000";

export type SortMode =
  | "relevance"
  | "n_samples_desc"
  | "submission_date_desc"
  | "submission_date_asc";

export type ConjunctionMode = "all" | "any";

export type SearchRequest = {
  query_text: string;
  // 비영어 쿼리 자동 영어번역. 기본 OFF(쿠키). 백엔드 default(True)를 프론트가 명시 override.
  auto_translate?: boolean;
  modality?: string[];
  organism_taxid?: number[];
  library_strategy?: string[];
  disease_ids?: string[];
  tissue_ids?: string[];
  cell_type_ids?: string[];
  source_db?: string[];
  access_preference?: "any" | "open_only";
  must_have_processed_data?: boolean;
  // Per-facet AND/OR mode. Omit or "any" = OR (backwards compat). "all" = AND.
  modality_conjunction_mode?: ConjunctionMode;
  disease_conjunction_mode?: ConjunctionMode;
  tissue_conjunction_mode?: ConjunctionMode;
  cell_type_conjunction_mode?: ConjunctionMode;
  organism_conjunction_mode?: ConjunctionMode;
  library_strategy_conjunction_mode?: ConjunctionMode;
  page?: number;
  page_size?: number;
  sort?: SortMode;
  lang?: "ko" | "en"; // AI Pick reason 언어(en/ko); 검색엔 무영향
};

export type ScoreBreakdown = {
  semantic: number | null;
  lexical: number | null;
  rrf: number;
  rerank?: number | null;
};

export type SourceRef = {
  source_db: string;
  source_id: string;
  raw_url: string | null;
  is_primary: boolean;
};

export type SearchResult = {
  dataset_id: string;
  source_db: string;
  source_id: string;
  title: string | null;
  abstract_snippet: string | null;
  score: number;
  score_breakdown: ScoreBreakdown;
  modality: string[];
  organism_taxid: number[];
  disease_ids?: string[];
  tissue_ids?: string[];
  cell_type_ids?: string[];
  library_strategy: string | null;
  platform: string | null;
  access_type: string;
  has_processed_data: boolean;
  submission_date: string | null;
  n_samples: number | null;
  sources?: SourceRef[];
};

export type FacetCount = { value: string; count: number };
export type Facets = {
  modality: FacetCount[];
  source_db: FacetCount[];
  disease_ids: FacetCount[];
  tissue_ids: FacetCount[];
  cell_type_ids: FacetCount[];
};

export type SearchResponse = {
  results: SearchResult[];
  facets: Facets;
  page: number;
  page_size: number;
  query_id: string;
  total_estimated: number;
  servable_total?: number; // 실제 페이지로 넘겨볼 수 있는 결과 수(서빙 윈도)
  latency_ms: number;
  // 자동 번역 발생 시 둘 다 set, 미발생 시 둘 다 null.
  original_query?: string | null;
  translated_query?: string | null;
};

export async function postSearch(
  body: SearchRequest,
  init?: { signal?: AbortSignal }
): Promise<SearchResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: init?.signal,
  });
  if (!resp.ok) {
    throw new Error(`Search failed: ${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as SearchResponse;
}

// ---- AI's Pick (project_ai_pick_feature.md) ----
// gemma4 가 검색 후보 중 엄선한 0..4 개 + 한 줄 이유. 클라이언트 island (AiPickCard)
// 가 /api/ai-pick BFF 로 POST. picks 가 [] 면 카드 자체를 숨긴다.

export type AIPickItem = {
  dataset_id: string;
  source_db: string;
  source_id: string;
  title: string | null;
  abstract_snippet: string | null;
  score: number;
  modality: string[];
  n_samples: number | null;
  reason: string; // gemma4 한국어 한 줄 추천 사유
};

export type AIPickResponse = {
  picks: AIPickItem[]; // 0..4 items
  cached: boolean;
  generated_at: string;
  model_version: string;
  query_id?: string | null;
};

export type DatasetDetail = {
  dataset_id: string;
  source_db: string;
  source_id: string;
  title: string | null;
  abstract: string | null;
  modality: string[];
  organism_taxid: number[];
  disease_ids?: string[];
  tissue_ids?: string[];
  cell_type_ids?: string[];
  library_strategy: string | null;
  platform: string | null;
  access_type: string;
  has_processed_data: boolean;
  has_raw_data: boolean;
  metadata_completeness: number;
  submission_date: string | null;
  last_update: string | null;
  n_samples: number | null;
  n_subjects: number | null;
  extraction_version: string;
  created_at: string | null;
  updated_at: string | null;
};

// `null` 반환 = 404. 그 외 에러는 throw.
export async function fetchDataset(id: string): Promise<DatasetDetail | null> {
  const resp = await fetch(`${API_BASE_URL}/api/v1/datasets/${id}`, { cache: "no-store" });
  if (resp.status === 404) return null;
  if (!resp.ok) {
    throw new Error(`Dataset fetch failed: ${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as DatasetDetail;
}

// curie 리스트 → label dict. 매칭 안 되는 curie 는 응답에서 빠짐 (caller 가 fallback 처리).
export async function fetchOntologyLabels(ids: string[]): Promise<Record<string, string>> {
  if (!ids.length) return {};
  const params = new URLSearchParams();
  for (const id of ids) params.append("ids", id);
  const resp = await fetch(`${API_BASE_URL}/api/v1/ontology/labels?${params.toString()}`, {
    cache: "no-store",
  });
  if (!resp.ok) return {};
  return (await resp.json()) as Record<string, string>;
}

// 랜딩 페이지의 "Database at a Glance" 데이터.
export type DashboardStats = {
  total_datasets: number;
  by_source: { source_db: string; count: number }[];
  extraction: { rich: number; stub: number; total: number; rich_pct: number };
  latest_datasets: {
    dataset_id: string;
    source_db: string;
    source_id: string;
    title: string;
    modality: string[];
    organism_taxid: number[];
    submission_date: string | null;
  }[];
  top_modalities: { value: string; count: number }[];
};

export async function fetchStats(): Promise<DashboardStats | null> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/v1/stats`, {
      next: { revalidate: 60 }, // 60초 ISR — landing 은 SSR 이지만 부담 줄임
    });
    if (!resp.ok) return null;
    return (await resp.json()) as DashboardStats;
  } catch {
    return null;
  }
}

// ---- Cohort / experimental design ----

export type CohortView = {
  samples: {
    n_total: number;
    sex: { male: number; female: number; unknown: number };
    age: {
      unit: "year" | "month" | "day" | null;
      min: number | null;
      max: number | null;
      median: number | null;
      buckets: { lo: number; hi: number; count: number }[];
    };
    disease_state: { label: string; count: number }[];
    treatment: { label: string; count: number }[];
  };
  design: {
    groups: {
      label: string;
      role: "case" | "control" | "treatment" | "comparison" | "other";
      n: number | null;
      criteria: string;
    }[];
    design_type: string;
    notes: string | null;
  } | null;
  design_version: string | null;
};

export async function fetchCohort(id: string): Promise<CohortView | null> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/v1/datasets/${id}/cohort`, {
      cache: "no-store",
    });
    if (resp.status === 404) return null;
    if (!resp.ok) return null;
    return (await resp.json()) as CohortView;
  } catch {
    return null;
  }
}

// ---- Translation (on-demand, ko only) ----

export type Translation = {
  dataset_id: string;
  lang: "ko";
  title: string | null;
  abstract: string | null;
};

// ---- Download snippets ----

export type Snippet = {
  language: "R" | "python" | "bash";
  title: string;
  description: string;
  code: string;
  requires: string[];
};

export type SourceSnippetGroup = {
  source_db: string;
  source_id: string;
  is_primary: boolean;
  snippets: Snippet[];
};

export type SnippetsResponse = {
  dataset_id: string;
  source_db: string;
  source_id: string;
  snippets: Snippet[];  // primary source 만 (backward compat)
  sources?: SourceSnippetGroup[];  // 모든 source 그룹 — UI selector 용
};

export async function fetchSnippets(id: string): Promise<SnippetsResponse | null> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/v1/datasets/${id}/snippets`, {
      cache: "no-store",
    });
    if (!resp.ok) return null;
    return (await resp.json()) as SnippetsResponse;
  } catch {
    return null;
  }
}

// 학술적 표시용 helper
export const TAXON_NAMES: Record<number, string> = {
  9606: "Homo sapiens",
  10090: "Mus musculus",
  10116: "Rattus norvegicus",
  7227: "Drosophila melanogaster",
  6239: "Caenorhabditis elegans",
  7955: "Danio rerio",
  4932: "Saccharomyces cerevisiae",
  562: "Escherichia coli",
  28901: "Salmonella enterica",
  1639: "Listeria monocytogenes",
};
