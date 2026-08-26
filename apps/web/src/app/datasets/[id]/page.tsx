import { AppShell } from "@/components/AppShell";
import { BackButton } from "@/components/BackButton";
import { CohortBreakdown } from "@/components/CohortBreakdown";
import { DownloadSnippets } from "@/components/DownloadSnippets";
import { ExperimentDesign } from "@/components/ExperimentDesign";
import { MetadataRichness } from "@/components/MetadataRichness";
import { PageTOC, type TocItem } from "@/components/PageTOC";
import { RecordView } from "@/components/RecordView";
import { SaveButton } from "@/components/SaveButton";
import {
  TranslatableAbstract,
  TranslatableTitle,
  TranslateProvider,
  TranslateToggleButton,
} from "@/components/TranslatableContent";
import {
  TAXON_NAMES,
  fetchCohort,
  fetchDataset,
  fetchOntologyLabels,
  fetchSnippets,
  type DatasetDetail,
} from "@/lib/api";
import { getT } from "@/lib/i18n-server";
import { sourceLinkLabel, sourceUrl as buildSourceUrl } from "@/lib/sourceLinks";

// GEO 플랫폼 숫자만 → "GPL{n}" 으로 보여주는 포맷터.
function formatPlatform(platform: string | null, sourceDb: string): string | null {
  if (!platform) return null;
  if (sourceDb === "GEO" && /^[0-9]+$/.test(platform)) return `GPL${platform}`;
  if (sourceDb === "GEO" && platform.includes(";")) {
    const first = platform.split(";")[0]?.trim() ?? platform;
    return /^[0-9]+$/.test(first) ? `GPL${first}` : first;
  }
  return platform;
}

export default async function DatasetDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const [{ locale, t }, p] = await Promise.all([getT(), params]);
  const id = p.id;

  let dataset: DatasetDetail | null = null;
  let errorMessage: string | null = null;
  try {
    dataset = await fetchDataset(id);
  } catch (err) {
    errorMessage = err instanceof Error ? err.message : "Unknown error";
  }

  const ontologyCuries = dataset
    ? [
        ...(dataset.disease_ids ?? []),
        ...(dataset.tissue_ids ?? []),
        ...(dataset.cell_type_ids ?? []),
      ]
    : [];
  const [ontologyLabels, cohort, snippets] = await Promise.all([
    fetchOntologyLabels(ontologyCuries).catch(() => ({}) as Record<string, string>),
    dataset ? fetchCohort(dataset.dataset_id) : Promise.resolve(null),
    dataset ? fetchSnippets(dataset.dataset_id) : Promise.resolve(null),
  ]);
  const labelOf = (curie: string): string => ontologyLabels[curie] ?? curie;

  // TOC 항목 — 본문 카드와 매칭되는 anchor.
  const toc: TocItem[] =
    locale === "ko"
      ? [
          { id: "summary", label: "요약" },
          { id: "metadata", label: "메타데이터" },
          { id: "cohort", label: "코호트" },
          { id: "design", label: "실험 디자인" },
          { id: "richness", label: "정보 풍부도" },
          { id: "download", label: "다운로드" },
          { id: "tech", label: "기술 정보" },
        ]
      : [
          { id: "summary", label: "Summary" },
          { id: "metadata", label: "Metadata" },
          { id: "cohort", label: "Cohort" },
          { id: "design", label: "Design" },
          { id: "richness", label: "Richness" },
          { id: "download", label: "Download" },
          { id: "tech", label: "Technical info" },
        ];

  const sourceUrl = dataset ? buildSourceUrl(dataset.source_db, dataset.source_id) : undefined;
  const platformDisp = dataset ? formatPlatform(dataset.platform, dataset.source_db) : null;

  return (
    <AppShell locale={locale} t={t}>
      <main className="mx-auto w-full max-w-6xl px-6 py-7 md:px-8">
        <BackButton label={t.datasetDetail.back} fallbackHref="/search" />

        {!dataset && !errorMessage ? (
          <div className="mt-7 rounded-xl border border-outline-variant bg-surface p-8">
            <p className="text-body-md text-on-surface-variant">
              {t.datasetDetail.notFound} <span className="font-mono">{id}</span>
              {t.datasetDetail.notFoundSuffix}
            </p>
            <p className="mt-2 text-body-sm text-on-surface-variant/70">
              {t.datasetDetail.notFoundHint}
            </p>
          </div>
        ) : null}

        {errorMessage ? (
          <div className="mt-7 rounded-xl border border-error/30 bg-error-container/40 p-5 text-on-error-container">
            <p className="font-medium">{t.datasetDetail.loadFail}</p>
            <p className="mt-1 font-mono text-body-sm">{errorMessage}</p>
          </div>
        ) : null}

        {dataset ? (
          <>
            <RecordView
              entry={{
                dataset_id: dataset.dataset_id,
                source_db: dataset.source_db,
                source_id: dataset.source_id,
                title: dataset.title,
                modality: dataset.modality,
                organism_taxid: dataset.organism_taxid,
              }}
            />

            <TranslateProvider
              datasetId={dataset.dataset_id}
              locale={locale}
              originalTitle={dataset.title}
              originalAbstract={dataset.abstract}
            >
            {/* ---- 헤더 카드 ---- */}
            <header className="mt-5 rounded-xl border border-outline-variant bg-surface p-7">
              <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 flex-col gap-2.5">
                  <div className="flex flex-wrap items-center gap-2 text-body-sm">
                    <span className="rounded-sm bg-tertiary-container px-1.5 py-0.5 text-label-caps uppercase text-on-tertiary-container">
                      {dataset.source_db}
                    </span>
                    <span className="font-mono text-mono-data text-on-surface-variant">
                      {dataset.source_id}
                    </span>
                    {dataset.submission_date ? (
                      <span className="font-mono text-mono-data text-on-surface-variant/70">
                        · {t.datasetDetail.submitted} {dataset.submission_date}
                      </span>
                    ) : null}
                    <span
                      className={`ml-1 rounded-md px-2 py-0.5 text-label-caps uppercase ${
                        dataset.access_type === "open"
                          ? "bg-secondary-container/60 text-on-secondary-container"
                          : "bg-error-container/40 text-on-error-container"
                      }`}
                    >
                      {dataset.access_type}
                    </span>
                  </div>
                  <TranslatableTitle
                    original={dataset.title}
                    fallback={t.result.noTitle}
                    className="text-headline-lg text-on-surface"
                  />
                  <div className="mt-1">
                    <TranslateToggleButton />
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-stretch gap-2 sm:flex-row sm:items-start">
                  <SaveButton
                    entry={{
                      dataset_id: dataset.dataset_id,
                      source_db: dataset.source_db,
                      source_id: dataset.source_id,
                      title: dataset.title,
                      modality: dataset.modality,
                      organism_taxid: dataset.organism_taxid,
                    }}
                    locale={locale}
                  />
                  {sourceUrl ? (
                    <a
                      href={sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex h-9 items-center justify-center gap-1 rounded-md bg-secondary px-3.5 text-body-sm font-medium text-on-secondary transition-colors hover:bg-secondary/90"
                    >
                      {t.datasetDetail.openIn} {sourceLinkLabel(dataset.source_db, dataset.source_id)} ↗
                    </a>
                  ) : null}
                </div>
              </div>

              {/* 4 metric tiles — 데이터셋 한눈에 */}
              <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MetricTile
                  label={locale === "ko" ? "출처" : "Source"}
                  value={dataset.source_db}
                />
                <MetricTile
                  label={t.datasetDetail.modality}
                  value={
                    dataset.modality.length > 0
                      ? dataset.modality.length === 1
                        ? dataset.modality[0] ?? "—"
                        : `${dataset.modality.length}${locale === "ko" ? "종" : ""}`
                      : "—"
                  }
                />
                <MetricTile
                  label={t.datasetDetail.organism}
                  value={
                    dataset.organism_taxid.length > 0
                      ? dataset.organism_taxid.length === 1
                        ? TAXON_NAMES[dataset.organism_taxid[0] ?? 0] ??
                          `taxid:${dataset.organism_taxid[0]}`
                        : `${dataset.organism_taxid.length}${locale === "ko" ? "종" : ""}`
                      : "—"
                  }
                />
                <MetricTile
                  label={t.datasetDetail.nSamples}
                  value={
                    dataset.n_samples != null && dataset.n_samples > 0
                      ? dataset.n_samples.toString()
                      : "—"
                  }
                />
              </div>
            </header>

            {/* ---- TOC + 본문 ---- */}
            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
              <div className="lg:col-span-3">
                <PageTOC
                  items={toc}
                  title={locale === "ko" ? "이 페이지에서" : "On this page"}
                />
              </div>

              <div className="flex flex-col gap-6 lg:col-span-9">
                {/* Summary */}
                <section
                  id="summary"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <h2 className="text-headline-sm text-on-surface">
                    {locale === "ko" ? "요약" : "Summary"}
                  </h2>
                  <TranslatableAbstract
                    original={dataset.abstract}
                    emptyText={
                      locale === "ko"
                        ? "초록이 제공되지 않았습니다."
                        : "No abstract provided."
                    }
                    className="mt-3 whitespace-pre-line text-body-md leading-relaxed text-on-surface"
                    emptyClassName="mt-3 text-body-sm text-on-surface-variant/70"
                  />
                </section>

                {/* Metadata */}
                <section
                  id="metadata"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <h2 className="text-headline-sm text-on-surface">
                    {locale === "ko" ? "메타데이터" : "Metadata"}
                  </h2>
                  <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
                    {dataset.modality.length > 0 ? (
                      <Field label={t.datasetDetail.modality}>
                        <ChipList items={dataset.modality} emerald />
                      </Field>
                    ) : null}
                    {dataset.organism_taxid.length > 0 ? (
                      <Field label={t.datasetDetail.organism}>
                        <ChipList
                          items={dataset.organism_taxid.map(
                            (id) => TAXON_NAMES[id] ?? `taxid:${id}`,
                          )}
                        />
                      </Field>
                    ) : null}
                    {(dataset.disease_ids?.length ?? 0) > 0 ? (
                      <Field label={locale === "ko" ? "질병" : "Disease"}>
                        <ChipList items={(dataset.disease_ids ?? []).map(labelOf)} />
                      </Field>
                    ) : null}
                    {(dataset.tissue_ids?.length ?? 0) > 0 ? (
                      <Field label={locale === "ko" ? "조직" : "Tissue"}>
                        <ChipList items={(dataset.tissue_ids ?? []).map(labelOf)} />
                      </Field>
                    ) : null}
                    {(dataset.cell_type_ids?.length ?? 0) > 0 ? (
                      <Field label={locale === "ko" ? "세포 타입" : "Cell type"}>
                        <ChipList items={(dataset.cell_type_ids ?? []).map(labelOf)} />
                      </Field>
                    ) : null}
                    {dataset.library_strategy ? (
                      <Field label={t.datasetDetail.libraryStrategy}>
                        <span>{dataset.library_strategy}</span>
                      </Field>
                    ) : null}
                    {platformDisp ? (
                      <Field label={t.datasetDetail.platform}>
                        <span className="font-mono text-mono-data">{platformDisp}</span>
                      </Field>
                    ) : null}
                    <Field label={t.datasetDetail.access}>
                      <span className="font-mono">{dataset.access_type}</span>
                    </Field>
                    <Field label={t.datasetDetail.hasProcessed}>
                      <span className="font-mono">
                        {dataset.has_processed_data
                          ? t.datasetDetail.yes
                          : t.datasetDetail.no}
                      </span>
                    </Field>
                  </div>
                  {/* organ/질병/세포 셋 다 비면 "아직 태깅 안 됨" 안내 (사용자 결정 2026-06-12).
                      '정보 없음'과 '표시 오류'를 구분해 사용자 혼란 방지. */}
                  {(dataset.disease_ids?.length ?? 0) === 0 &&
                  (dataset.tissue_ids?.length ?? 0) === 0 &&
                  (dataset.cell_type_ids?.length ?? 0) === 0 ? (
                    <p className="mt-4 rounded-lg border border-outline-variant bg-surface-variant/40 px-3 py-2 text-body-sm text-on-surface-variant">
                      {t.datasetDetail.notTagged}
                    </p>
                  ) : null}
                </section>

                {/* Cohort breakdown — sample 단위 분포 */}
                <section
                  id="cohort"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <CohortBreakdown
                    samples={
                      cohort?.samples ?? {
                        n_total: 0,
                        sex: { male: 0, female: 0, unknown: 0 },
                        age: { unit: null, min: null, max: null, median: null, buckets: [] },
                        disease_state: [],
                        treatment: [],
                      }
                    }
                    sourceSampleCount={dataset.n_samples}
                    locale={locale}
                  />
                </section>

                {/* Experiment design — LLM 추출 */}
                <section
                  id="design"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <ExperimentDesign
                    design={cohort?.design ?? null}
                    datasetId={dataset.dataset_id}
                    locale={locale}
                  />
                </section>

                {/* Metadata Richness */}
                <section
                  id="richness"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <MetadataRichness dataset={dataset} locale={locale} />
                </section>

                {/* Download snippets */}
                <section
                  id="download"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <DownloadSnippets data={snippets} locale={locale} />
                </section>

                {/* Technical info */}
                <section
                  id="tech"
                  className="scroll-mt-20 rounded-xl border border-outline-variant bg-surface p-6"
                >
                  <h2 className="text-headline-sm text-on-surface">
                    {locale === "ko" ? "기술 정보" : "Technical info"}
                  </h2>
                  <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-body-sm">
                    <dt className="text-on-surface-variant">
                      {locale === "ko" ? "추출 버전" : "extraction_version"}
                    </dt>
                    <dd className="text-right font-mono text-mono-data text-on-surface">
                      {dataset.extraction_version}
                    </dd>
                    <dt className="text-on-surface-variant">dataset_id</dt>
                    <dd className="truncate text-right font-mono text-mono-data text-on-surface">
                      {dataset.dataset_id}
                    </dd>
                    {dataset.last_update ? (
                      <>
                        <dt className="text-on-surface-variant">
                          {locale === "ko" ? "최종 갱신" : "last_update"}
                        </dt>
                        <dd className="text-right font-mono text-mono-data text-on-surface">
                          {dataset.last_update}
                        </dd>
                      </>
                    ) : null}
                    {dataset.created_at ? (
                      <>
                        <dt className="text-on-surface-variant">
                          {locale === "ko" ? "최초 색인" : "first_indexed"}
                        </dt>
                        <dd className="text-right font-mono text-mono-data text-on-surface">
                          {dataset.created_at.split("T")[0]}
                        </dd>
                      </>
                    ) : null}
                  </dl>
                </section>
              </div>
            </div>
            </TranslateProvider>
          </>
        ) : null}
      </main>
    </AppShell>
  );
}

// ---------------------------------------------------------------------------
// pieces
// ---------------------------------------------------------------------------

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-outline-variant bg-surface-container-low/60 px-4 py-3">
      <div className="text-label-caps uppercase text-on-surface-variant">{label}</div>
      <div className="mt-0.5 truncate text-body-md font-medium text-on-surface" title={value}>
        {value}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-label-caps uppercase text-on-surface-variant">{label}</div>
      <div className="mt-1.5 text-body-md text-on-surface">{children}</div>
    </div>
  );
}

function ChipList({
  items,
  emerald = false,
}: {
  items: string[];
  emerald?: boolean;
}) {
  if (!items.length) return null;
  const cls = emerald
    ? "bg-secondary-container/60 text-on-secondary-container"
    : "bg-surface-container text-on-surface-variant";
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it) => (
        <span key={it} className={`rounded-md px-2 py-0.5 text-body-sm ${cls}`}>
          {it}
        </span>
      ))}
    </div>
  );
}
