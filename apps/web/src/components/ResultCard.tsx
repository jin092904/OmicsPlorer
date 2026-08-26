import Link from "next/link";

import { TAXON_NAMES, type SearchResult } from "@/lib/api";
import type { Locale, T } from "@/lib/i18n";
import { sourceUrl as buildSourceUrl } from "@/lib/sourceLinks";

import { SaveButton } from "./SaveButton";
import { ScoreBreakdown } from "./ScoreBreakdown";

const SOURCE_BADGE_CLASS: Record<string, string> = {
  GEO: "bg-tertiary-container text-on-tertiary-container",
  SRA: "bg-secondary-container text-on-secondary-container",
  HCA: "bg-error-container text-on-error-container",
  GDC: "bg-primary-container text-on-primary-container",
  ENA: "bg-surface-container-high text-on-surface-variant",
};

export function ResultCard({
  result,
  t,
  locale,
  ontologyLabels,
}: {
  result: SearchResult;
  t: T;
  locale: Locale;
  ontologyLabels?: Record<string, string>;
}) {
  const labelOf = (curie: string) => ontologyLabels?.[curie] ?? curie;
  const sourceUrl = buildSourceUrl(result.source_db, result.source_id);
  const sourceBadge = SOURCE_BADGE_CLASS[result.source_db] ?? "bg-surface-container-high text-on-surface-variant";
  const taxonNames = result.organism_taxid
    .map((id) => TAXON_NAMES[id] ?? `taxid:${id}`)
    .filter((s) => s.length > 0);

  return (
    <article className="flex flex-col gap-4 rounded-xl border border-outline-variant bg-surface p-6 transition-shadow hover:shadow-card-hover">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2 text-body-sm">
            <span className={`rounded-sm px-1.5 py-0.5 text-label-caps uppercase ${sourceBadge}`}>
              {result.source_db}
            </span>
            <Link
              href={`/datasets/${result.dataset_id}`}
              className="font-mono text-mono-data text-on-surface-variant transition-colors hover:text-secondary"
            >
              {result.source_id}
            </Link>
            {/* 추가 source 배지 (primary 와 다른 source_db 만) */}
            {(result.sources ?? [])
              .filter((s) => s.source_db !== result.source_db)
              .map((s) => (
                <a
                  key={`${s.source_db}:${s.source_id}`}
                  href={s.raw_url ?? buildSourceUrl(s.source_db, s.source_id) ?? "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  title={`${s.source_db}: ${s.source_id}`}
                  className={`rounded-sm px-1.5 py-0.5 text-label-caps uppercase transition-opacity hover:opacity-80 ${
                    SOURCE_BADGE_CLASS[s.source_db] ?? "bg-surface-container-high text-on-surface-variant"
                  }`}
                >
                  {s.source_db}
                </a>
              ))}
            {result.submission_date ? (
              <span className="font-mono text-mono-data text-on-surface-variant/70">
                · {result.submission_date}
              </span>
            ) : null}
          </div>
          <h3 className="text-headline-sm text-on-surface">
            <Link
              href={`/datasets/${result.dataset_id}`}
              className="transition-colors hover:text-secondary"
            >
              {result.title || t.result.noTitle}
            </Link>
          </h3>
        </div>
        <SaveButton
          entry={{
            dataset_id: result.dataset_id,
            source_db: result.source_db,
            source_id: result.source_id,
            title: result.title,
            modality: result.modality,
            organism_taxid: result.organism_taxid,
          }}
          locale={locale}
          size="sm"
        />
      </div>

      {result.abstract_snippet ? (
        <p className="line-clamp-3 text-body-md text-on-surface-variant">
          {result.abstract_snippet}
        </p>
      ) : null}

      {(result.modality.length > 0 ||
        (result.disease_ids?.length ?? 0) > 0 ||
        (result.tissue_ids?.length ?? 0) > 0 ||
        (result.cell_type_ids?.length ?? 0) > 0 ||
        taxonNames.length > 0 ||
        result.platform ||
        result.library_strategy ||
        result.has_processed_data ||
        result.n_samples) ? (
        <div className="flex flex-wrap items-center gap-1.5 text-body-sm">
          {result.modality.map((m) => (
            <span
              key={m}
              className="rounded-md bg-secondary-container/60 px-2 py-0.5 text-on-secondary-container"
            >
              {m}
            </span>
          ))}
          {(result.disease_ids ?? []).map((curie) => (
            <span
              key={curie}
              className="rounded-md bg-error-container/60 px-2 py-0.5 text-on-error-container"
              title={curie}
            >
              {labelOf(curie)}
            </span>
          ))}
          {(result.tissue_ids ?? []).map((curie) => (
            <span
              key={curie}
              className="rounded-md bg-tertiary-container/60 px-2 py-0.5 text-on-tertiary-container"
              title={curie}
            >
              {labelOf(curie)}
            </span>
          ))}
          {(result.cell_type_ids ?? []).map((curie) => (
            <span
              key={curie}
              className="rounded-md bg-primary-container/15 px-2 py-0.5 text-on-surface-variant"
              title={curie}
            >
              {labelOf(curie)}
            </span>
          ))}
          {taxonNames.map((name) => (
            <span
              key={name}
              className="rounded-md bg-surface-container px-2 py-0.5 italic text-on-surface-variant"
            >
              {name}
            </span>
          ))}
          {result.library_strategy ? (
            <span className="rounded-md bg-surface-container px-2 py-0.5 font-mono text-mono-data text-on-surface-variant">
              {result.library_strategy}
            </span>
          ) : null}
          {result.has_processed_data ? (
            <span className="rounded-md bg-surface-container px-2 py-0.5 text-on-surface-variant">
              {t.result.processed}
            </span>
          ) : null}
          {result.n_samples ? (
            <span className="rounded-md bg-surface-container px-2 py-0.5 font-mono text-mono-data text-on-surface-variant">
              n={result.n_samples}
            </span>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-end justify-between gap-4 border-t border-outline-variant pt-4">
        <div className="w-full max-w-xl">
          <ScoreBreakdown breakdown={result.score_breakdown} t={t} locale={locale} />
        </div>
        {sourceUrl ? (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 rounded-md border border-outline-variant px-3 py-1.5 text-body-sm font-medium text-on-surface-variant transition-colors hover:border-secondary hover:text-secondary"
          >
            {t.result.sourceLink}
          </a>
        ) : null}
      </div>
    </article>
  );
}
