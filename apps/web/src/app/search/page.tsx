import { AiPickCard } from "@/components/AiPickCard";
import { AppShell } from "@/components/AppShell";
import { AutoTranslateToggle } from "@/components/AutoTranslateToggle";
import { Filters } from "@/components/Filters";
import { SearchPendingOverlay } from "@/components/NavigationPending";
import { Pagination } from "@/components/Pagination";
import { ResultCard } from "@/components/ResultCard";
import { SortMenu } from "@/components/SortMenu";
import { fetchOntologyLabels, postSearch, type SearchRequest, type SortMode } from "@/lib/api";
import { getAutoTranslate, getT } from "@/lib/i18n-server";

const VALID_SORTS: SortMode[] = [
  "relevance",
  "n_samples_desc",
  "submission_date_desc",
  "submission_date_asc",
];

type SearchPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

const PAGE_SIZE = 20;

function asArray(v: string | string[] | undefined): string[] {
  if (v == null) return [];
  return Array.isArray(v) ? v : [v];
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const [{ locale, t }, params, autoTranslate] = await Promise.all([
    getT(),
    searchParams,
    getAutoTranslate(),
  ]);
  const query = (typeof params.q === "string" ? params.q : "").trim();
  const modality = asArray(params.modality);
  const sourceDb = asArray(params.source_db);
  const disease = asArray(params.disease);
  const tissue = asArray(params.tissue);
  const cellType = asArray(params.cell_type);
  const accessPreference = (params.access === "any" ? "any" : "open_only") as
    | "any"
    | "open_only";
  const mustHaveProcessedData = params.processed === "1";
  // Conjunction (AND) modes per facet. URL param value is literal "all"; absence = OR.
  // Guarded by selectedCount >= 2 so a stale URL doesn't silently keep AND after deselect.
  const asConj = (raw: string | string[] | undefined, selectedCount: number) =>
    raw === "all" && selectedCount >= 2 ? ("all" as const) : null;
  const conjunctionModes = {
    modality: asConj(params.modality_conjunction, modality.length),
    disease: asConj(params.disease_conjunction, disease.length),
    tissue: asConj(params.tissue_conjunction, tissue.length),
    cell_type: asConj(params.cell_type_conjunction, cellType.length),
  };
  const page = Math.max(1, parseInt((params.page as string) ?? "1", 10) || 1);
  const sortParam = typeof params.sort === "string" ? params.sort : "relevance";
  const sort: SortMode = (VALID_SORTS as string[]).includes(sortParam)
    ? (sortParam as SortMode)
    : "relevance";

  let response: Awaited<ReturnType<typeof postSearch>> | null = null;
  let errorMessage: string | null = null;
  if (query) {
    const reqBody: SearchRequest = {
      query_text: query,
      auto_translate: autoTranslate, // 기본 OFF; 사용자가 토글로 켤 때만 True
      modality: modality.length ? modality : undefined,
      disease_ids: disease.length ? disease : undefined,
      tissue_ids: tissue.length ? tissue : undefined,
      cell_type_ids: cellType.length ? cellType : undefined,
      source_db: sourceDb.length ? sourceDb : undefined,
      access_preference: accessPreference,
      must_have_processed_data: mustHaveProcessedData,
      modality_conjunction_mode: conjunctionModes.modality ?? undefined,
      disease_conjunction_mode: conjunctionModes.disease ?? undefined,
      tissue_conjunction_mode: conjunctionModes.tissue ?? undefined,
      cell_type_conjunction_mode: conjunctionModes.cell_type ?? undefined,
      page,
      page_size: PAGE_SIZE,
      sort,
    };
    try {
      response = await postSearch(reqBody);
    } catch (err) {
      errorMessage = err instanceof Error ? err.message : "Unknown search error";
    }
  }

  // source_db 는 이제 서버측 필터(reqBody.source_db)로 처리 → 클라이언트 재필터 불필요.
  // (이전: 페이지 fetch 후 client filter → 빈 페이지/페이지수 불일치 버그)
  const filteredResults = response?.results ?? [];

  // facet curie + 선택된 ontology + 결과별 disease/tissue/cell_type id → 라벨 lookup
  const allOntologyCuries: string[] = [...disease, ...tissue, ...cellType];
  if (response) {
    allOntologyCuries.push(
      ...response.facets.disease_ids.map((f) => f.value),
      ...response.facets.tissue_ids.map((f) => f.value),
      ...response.facets.cell_type_ids.map((f) => f.value),
    );
    for (const r of response.results) {
      if (r.disease_ids) allOntologyCuries.push(...r.disease_ids);
      if (r.tissue_ids) allOntologyCuries.push(...r.tissue_ids);
      if (r.cell_type_ids) allOntologyCuries.push(...r.cell_type_ids);
    }
  }
  const ontologyLabels: Record<string, string> = await fetchOntologyLabels(allOntologyCuries).catch(
    () => ({}),
  );

  return (
    <AppShell locale={locale} t={t} initialQuery={query}>
      <main className="grid w-full grid-cols-1 gap-7 px-6 py-7 md:grid-cols-12">
        <div className="md:col-span-3">
          <Filters
            selectedModality={modality}
            selectedSourceDb={sourceDb}
            selectedDisease={disease}
            selectedTissue={tissue}
            selectedCellType={cellType}
            accessPreference={accessPreference}
            mustHaveProcessedData={mustHaveProcessedData}
            conjunctionModes={conjunctionModes}
            query={query}
            t={t}
            facets={response?.facets}
            locale={locale}
            ontologyLabels={ontologyLabels}
          />
        </div>
        <section className="relative flex flex-col gap-4 md:col-span-9">
          <SearchPendingOverlay locale={locale} />
          <header className="mb-1">
            <h1 className="text-headline-md text-on-surface">
              {query ? (
                <>
                  {t.search.titlePrefix}{" "}
                  <span className="text-secondary">&ldquo;{query}&rdquo;</span>
                </>
              ) : (
                t.search.titleEmpty
              )}
            </h1>
            {response ? (
              <>
                {response.translated_query && response.original_query ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-secondary/30 bg-secondary-container/20 px-3 py-2 text-body-sm">
                    <span aria-hidden>↗</span>
                    <span className="text-on-surface-variant">
                      {locale === "ko" ? "자동 번역됨:" : "Auto-translated:"}
                    </span>
                    <span className="font-mono text-on-surface-variant/80">
                      {response.original_query}
                    </span>
                    <span className="text-on-surface-variant/60">→</span>
                    <span className="font-mono font-medium text-on-surface">
                      {response.translated_query}
                    </span>
                  </div>
                ) : null}
                <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
                  <p role="status" aria-live="polite" className="text-body-sm text-on-surface-variant">
                    {filteredResults.length === response.results.length ? (
                      <>
                        {/* 주 카운트 = 실제 열람 가능 건수(servable_total). total_estimated(코퍼스 전체 매칭)는
                            페이지 수와 700배까지 어긋나 오해를 줘서 주 표기에서 제외(2026-07-03). */}
                        <span className="font-mono font-medium text-on-surface">
                          {response.servable_total ?? response.total_estimated}
                        </span>{" "}
                        {t.search.summaryCandidates}
                      </>
                    ) : (
                      <>
                        <span className="font-mono font-medium text-on-surface">
                          {filteredResults.length}
                        </span>{" "}
                        {t.search.summaryFilteredOf}
                        {response.results.length}
                        {t.search.summaryFilteredOfSuffix}
                      </>
                    )}{" "}
                    <span className="text-on-surface-variant/60">
                      · <span className="font-mono">{response.latency_ms}ms</span>
                    </span>
                  </p>
                  <SortMenu current={sort} locale={locale} />
                </div>
                {/* 자동번역 토글 + 영어검색 권장 문구 (요구②) */}
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <AutoTranslateToggle enabled={autoTranslate} />
                  <span className="text-body-sm text-on-surface-variant/60">
                    Tip: search works best in English.
                  </span>
                </div>
              </>
            ) : !query ? (
              <p className="mt-2 text-body-md text-on-surface-variant">{t.search.placeholderHelp}</p>
            ) : null}
          </header>

          {errorMessage ? (
            <div role="alert" className="rounded-xl border border-error/30 bg-error-container/40 p-5 text-on-error-container">
              <p className="font-medium">{t.search.errorTitle}</p>
              <p className="mt-1 font-mono text-body-sm">{errorMessage}</p>
              <p className="mt-2 text-body-sm">{t.search.errorHint}</p>
            </div>
          ) : null}

          {response && filteredResults.length === 0 && !errorMessage ? (
            <div className="rounded-xl border border-outline-variant bg-surface p-10 text-center">
              {(() => {
                // 범위 초과 페이지(깊은 page 인데 결과 0): 첫 페이지로 복구 안내(빈 화면 + 거대 카운트 모순 해소).
                if (page > 1) {
                  const sp1 = new URLSearchParams();
                  for (const [k, v] of Object.entries(params)) {
                    if (v == null || k === "page") continue;
                    if (Array.isArray(v)) {
                      for (const item of v) sp1.append(k, item);
                    } else {
                      sp1.set(k, v);
                    }
                  }
                  return (
                    <>
                      <p className="text-body-md text-on-surface-variant">
                        {locale === "ko"
                          ? "이 페이지는 검색 범위를 벗어났습니다."
                          : "This page is beyond the available range."}
                      </p>
                      <a
                        href={`/search?${sp1.toString()}`}
                        className="mt-3 inline-block rounded-full border border-secondary px-3 py-1 text-body-sm text-secondary transition-colors hover:bg-secondary-container/30"
                      >
                        {locale === "ko" ? "첫 페이지로" : "Back to first page"}
                      </a>
                    </>
                  );
                }
                const activeAnd = (
                  Object.entries(conjunctionModes) as [
                    keyof typeof conjunctionModes,
                    "all" | null,
                  ][]
                )
                  .filter(([, v]) => v === "all")
                  .map(([k]) => k);
                if (activeAnd.length > 0) {
                  // Rebuild href without the AND conjunction params for active facets.
                  const sp = new URLSearchParams();
                  for (const [k, v] of Object.entries(params)) {
                    if (v == null) continue;
                    const key = k as string;
                    if (activeAnd.some((f) => key === `${f}_conjunction`)) continue;
                    if (Array.isArray(v)) {
                      for (const item of v) sp.append(key, item);
                    } else {
                      sp.set(key, v);
                    }
                  }
                  return (
                    <>
                      <p className="text-body-md text-on-surface-variant">
                        {t.filters.andEmptyMessage}
                      </p>
                      <a
                        href={`/search?${sp.toString()}`}
                        className="mt-3 inline-block rounded-full border border-secondary px-3 py-1 text-body-sm text-secondary transition-colors hover:bg-secondary-container/30"
                      >
                        {t.filters.andEmptyRevert}
                      </a>
                    </>
                  );
                }
                return (
                  <>
                    <p className="text-body-md text-on-surface-variant">{t.search.noResults}</p>
                    <p className="mt-2 text-body-sm text-on-surface-variant/70">{t.search.noResultsHint}</p>
                  </>
                );
              })()}
            </div>
          ) : null}

          {query && filteredResults.length > 0 ? (
            <AiPickCard
              query={query}
              filters={{
                modality: modality.length ? modality : undefined,
                disease_ids: disease.length ? disease : undefined,
                tissue_ids: tissue.length ? tissue : undefined,
                cell_type_ids: cellType.length ? cellType : undefined,
                source_db: sourceDb.length ? sourceDb : undefined,
                access_preference: accessPreference,
                must_have_processed_data: mustHaveProcessedData,
                modality_conjunction_mode: conjunctionModes.modality ?? undefined,
                disease_conjunction_mode: conjunctionModes.disease ?? undefined,
                tissue_conjunction_mode: conjunctionModes.tissue ?? undefined,
                cell_type_conjunction_mode: conjunctionModes.cell_type ?? undefined,
              }}
              locale={locale}
            />
          ) : null}

          {filteredResults.map((r) => (
            <ResultCard
              key={r.dataset_id}
              result={r}
              t={t}
              locale={locale}
              ontologyLabels={ontologyLabels}
            />
          ))}

          {response && filteredResults.length > 0 ? (
            <Pagination
              page={response.page}
              pageSize={response.page_size}
              total={response.servable_total ?? response.total_estimated}
              locale={locale}
            />
          ) : null}
        </section>
      </main>
    </AppShell>
  );
}
