import Link from "next/link";

import { TAXON_NAMES, type DashboardStats } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

// 랜딩 페이지의 "Database at a Glance" 섹션 + 최근 데이터셋 + 추천 쿼리.
// 메인 페이지가 hero (검색) 만 있던 것을 "현시점 트렌드/소식" 으로 보강.
export function DashboardOverview({
  stats,
  locale,
}: {
  stats: DashboardStats | null;
  locale: Locale;
}) {
  const labels =
    locale === "ko"
      ? {
          glance: "데이터베이스 현황",
          totalDatasets: "인덱싱된 데이터셋",
          totalSub: "현재 검색 인덱스의 1차 출처",
          sources: "출처 DB",
          richExtraction: "구조화된 메타데이터",
          richSub: "검색·필터에 사용할 수 있는 메타데이터",
          recent: "최근 추가된 데이터셋",
          recentSub: "출처 제출일 기준 최신순",
          recentEmpty: "최근 데이터셋이 없습니다.",
          trending: "추천 검색어",
          trendingSub: "지금 바로 시도해 볼 수 있는 검색어입니다.",
          viewAll: "모두 보기 →",
        }
      : {
          glance: "Database at a glance",
          totalDatasets: "Indexed datasets",
          totalSub: "Primary sources in the current search index",
          sources: "Source DBs",
          richExtraction: "Structured metadata",
          richSub: "Metadata available for search and filtering",
          recent: "Recently added datasets",
          recentSub: "Newest by submission date",
          recentEmpty: "No recent datasets.",
          trending: "Suggested queries",
          trendingSub: "Try one of these to get started",
          viewAll: "View all →",
        };

  const suggestions =
    locale === "ko"
      ? [
          { q: "단일세포 RNA-seq 인간 PBMC 면역", desc: "scRNA-seq, 면역 세포" },
          { q: "췌장 islet 인슐린", desc: "당뇨 / 내분비 연구" },
          { q: "ChIP-seq H3K4me3 transcription", desc: "에피지놈 마커" },
          { q: "tumor microenvironment macrophage", desc: "종양 면역 미세환경" },
          { q: "bacterial whole genome sequencing", desc: "박테리아 게놈" },
          { q: "spatial transcriptomics brain cortex", desc: "공간 전사체" },
        ]
      : [
          { q: "single-cell RNA-seq human PBMC immune", desc: "scRNA-seq, immune cells" },
          { q: "pancreatic islet insulin", desc: "Diabetes / endocrine" },
          { q: "ChIP-seq H3K4me3 transcription", desc: "Epigenetic marks" },
          { q: "tumor microenvironment macrophage", desc: "Tumor immune niche" },
          { q: "bacterial whole genome sequencing", desc: "Bacterial genomes" },
          { q: "spatial transcriptomics brain cortex", desc: "Spatial transcriptomics" },
        ];

  // total 이 큰 GEO/HCA 두 개만 강조, 나머지는 합산해서 표시.
  const sourceBreakdown = stats?.by_source ?? [];
  const sourceCount = sourceBreakdown.length;
  const indexedSources = sourceBreakdown.map((s) => s.source_db).join(" · ") || "—";

  return (
    <div className="flex flex-col gap-12">
      {/* Database at a Glance */}
      <section>
        <h2 className="text-headline-sm text-on-surface">{labels.glance}</h2>
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
          <MetricCard
            label={labels.totalDatasets}
            value={stats ? formatCompact(stats.total_datasets) : "—"}
            sub={`${labels.totalSub}: ${indexedSources}`}
            accent="primary"
          />
          <MetricCard
            label={labels.sources}
            value={sourceCount.toString()}
            sub={
              sourceBreakdown
                .map((s) => `${s.source_db} ${formatCompact(s.count)}`)
                .join(" · ") || "—"
            }
            accent="tertiary"
          />
          <MetricCard
            label={labels.richExtraction}
            value={stats ? `${stats.extraction.rich_pct}%` : "—"}
            sub={
              stats
                ? `${formatCompact(stats.extraction.rich)} / ${formatCompact(stats.extraction.total)} · ${labels.richSub}`
                : labels.richSub
            }
            accent="secondary"
            progressPct={stats?.extraction.rich_pct ?? null}
          />
        </div>
      </section>

      {/* 두 컬럼: 최근 데이터셋 + 추천 검색어 */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 최근 데이터셋 */}
        <div className="flex flex-col rounded-xl border border-outline-variant bg-surface p-5">
          <header className="flex items-baseline justify-between gap-3">
            <div>
              <h3 className="text-headline-sm text-on-surface">{labels.recent}</h3>
              <p className="mt-0.5 text-body-sm text-on-surface-variant">{labels.recentSub}</p>
            </div>
            <Link
              href="/search"
              className="shrink-0 text-body-sm font-medium text-secondary transition-opacity hover:opacity-70"
            >
              {labels.viewAll}
            </Link>
          </header>
          <ul className="mt-4 flex flex-col gap-1">
            {stats?.latest_datasets?.length ? (
              stats.latest_datasets.slice(0, 5).map((d) => (
                <li key={d.dataset_id}>
                  <Link
                    href={`/datasets/${d.dataset_id}`}
                    className="-mx-2 flex flex-col gap-1 rounded-md px-2 py-2.5 transition-colors hover:bg-surface-container"
                  >
                    <div className="flex items-center gap-2 text-body-sm">
                      <span className="rounded-sm bg-tertiary-container/80 px-1.5 py-0.5 text-label-caps uppercase text-on-tertiary-container">
                        {d.source_db}
                      </span>
                      <span className="font-mono text-mono-data text-on-surface-variant">
                        {d.source_id}
                      </span>
                      {d.submission_date ? (
                        <span className="font-mono text-mono-data text-on-surface-variant/70">
                          · {d.submission_date}
                        </span>
                      ) : null}
                    </div>
                    <div className="line-clamp-2 text-body-md text-on-surface">
                      {d.title || (locale === "ko" ? "(제목 없음)" : "(no title)")}
                    </div>
                    {d.organism_taxid.length > 0 || d.modality.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5 text-body-sm">
                        {d.modality.slice(0, 3).map((m) => (
                          <span
                            key={m}
                            className="rounded-md bg-secondary-container/60 px-2 py-0.5 text-on-secondary-container"
                          >
                            {m}
                          </span>
                        ))}
                        {d.organism_taxid
                          .slice(0, 2)
                          .map((id) => TAXON_NAMES[id] ?? `taxid:${id}`)
                          .map((n) => (
                            <span
                              key={n}
                              className="rounded-md bg-surface-container px-2 py-0.5 italic text-on-surface-variant"
                            >
                              {n}
                            </span>
                          ))}
                      </div>
                    ) : null}
                  </Link>
                </li>
              ))
            ) : (
              <li className="py-6 text-center text-body-sm text-on-surface-variant">
                {labels.recentEmpty}
              </li>
            )}
          </ul>
        </div>

        {/* 추천 쿼리 */}
        <div className="flex flex-col rounded-xl border border-outline-variant bg-surface p-5">
          <header>
            <h3 className="text-headline-sm text-on-surface">{labels.trending}</h3>
            <p className="mt-0.5 text-body-sm text-on-surface-variant">{labels.trendingSub}</p>
          </header>
          <ul className="mt-4 flex flex-col gap-1">
            {suggestions.map((s) => (
              <li key={s.q}>
                <Link
                  href={`/search?q=${encodeURIComponent(s.q)}`}
                  className="-mx-2 flex items-start gap-3 rounded-md px-2 py-2.5 transition-colors hover:bg-surface-container"
                >
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary-container/60 text-on-secondary-container">
                    <SearchIcon />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body-md text-on-surface">{s.q}</span>
                    <span className="block text-body-sm text-on-surface-variant">{s.desc}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>

          {stats?.top_modalities?.length ? (
            <div className="mt-5 border-t border-outline-variant pt-4">
              <p className="text-label-caps uppercase text-on-surface-variant">
                {locale === "ko" ? "코퍼스 인기 모달리티" : "Top modalities in corpus"}
              </p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {stats.top_modalities.map((m) => (
                  <Link
                    key={m.value}
                    href={`/search?q=${encodeURIComponent(m.value)}&modality=${encodeURIComponent(m.value)}`}
                    className="flex items-center gap-1.5 rounded-md bg-tertiary-container/60 px-2.5 py-1 text-body-sm text-on-tertiary-container transition-colors hover:bg-tertiary-container"
                  >
                    <span>{m.value}</span>
                    <span className="font-mono text-mono-data opacity-70">
                      {formatCompact(m.count)}
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// pieces
// ---------------------------------------------------------------------------

function MetricCard({
  label,
  value,
  sub,
  accent,
  progressPct,
}: {
  label: string;
  value: string;
  sub: string;
  accent: "primary" | "secondary" | "tertiary";
  progressPct?: number | null;
}) {
  const accentText = {
    primary: "text-on-surface",
    secondary: "text-secondary",
    tertiary: "text-tertiary",
  }[accent];

  return (
    <article className="flex flex-col rounded-xl border border-outline-variant bg-surface p-5">
      <span className="text-label-caps uppercase text-on-surface-variant">{label}</span>
      <span
        className={`mt-2 font-mono text-on-surface ${accentText}`}
        style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-0.01em" }}
      >
        {value}
      </span>
      <span className="mt-1.5 line-clamp-2 text-body-sm text-on-surface-variant">{sub}</span>
      {progressPct != null ? (
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-container-high">
          <div
            className="h-full rounded-full bg-secondary"
            style={{ width: `${Math.max(2, Math.min(100, progressPct))}%` }}
          />
        </div>
      ) : null}
    </article>
  );
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}K`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

function SearchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
