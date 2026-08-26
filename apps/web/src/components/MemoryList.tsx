"use client";

import Link from "next/link";

import { TAXON_NAMES } from "@/lib/api";
import {
  useRecentlyViewed,
  useSavedDatasets,
  type DatasetMemoryEntry,
} from "@/lib/datasetMemory";

const SOURCE_BADGE_CLASS: Record<string, string> = {
  GEO: "bg-tertiary-container text-on-tertiary-container",
  SRA: "bg-secondary-container text-on-secondary-container",
  HCA: "bg-error-container text-on-error-container",
  GDC: "bg-primary-container text-on-primary-container",
  ENA: "bg-surface-container-high text-on-surface-variant",
};

export function MemoryList({
  kind,
  locale,
}: {
  kind: "recent" | "saved";
  locale: "ko" | "en";
}) {
  const recent = useRecentlyViewed();
  const saved = useSavedDatasets();
  const items = kind === "recent" ? recent.items : saved.items;
  const clear = kind === "recent" ? recent.clear : saved.clear;

  const labels =
    locale === "ko"
      ? {
          empty: kind === "recent" ? "아직 본 데이터셋이 없습니다." : "찜한 데이터셋이 없습니다.",
          emptyHint:
            kind === "recent"
              ? "검색 결과에서 데이터셋을 열어 보면 여기에 기록됩니다."
              : "결과 카드의 하트 버튼을 눌러 데이터셋을 찜할 수 있습니다.",
          clear: kind === "recent" ? "기록 비우기" : "전체 해제",
        }
      : {
          empty: kind === "recent" ? "Nothing viewed yet." : "No saved datasets yet.",
          emptyHint:
            kind === "recent"
              ? "Click a dataset from search to record it here."
              : "Use the heart icon on a result card to save it.",
          clear: "Clear all",
        };

  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-outline-variant bg-surface p-10 text-center">
        <p className="text-body-md text-on-surface-variant">{labels.empty}</p>
        <p className="mt-2 text-body-sm text-on-surface-variant/70">{labels.emptyHint}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={clear}
          className="text-body-sm font-medium text-on-surface-variant transition-colors hover:text-error"
        >
          {labels.clear}
        </button>
      </div>
      {items.map((entry) => (
        <MemoryItem key={entry.dataset_id} entry={entry} kind={kind} locale={locale} />
      ))}
    </div>
  );
}

function MemoryItem({
  entry,
  kind,
  locale,
}: {
  entry: DatasetMemoryEntry;
  kind: "recent" | "saved";
  locale: "ko" | "en";
}) {
  const { remove } = useSavedDatasets();
  const taxonNames = entry.organism_taxid
    .map((id) => TAXON_NAMES[id] ?? `taxid:${id}`)
    .filter((s) => s.length > 0);
  const sourceBadge = SOURCE_BADGE_CLASS[entry.source_db] ?? "bg-surface-container-high text-on-surface-variant";
  const dateStr = new Date(entry.ts).toLocaleString(locale === "ko" ? "ko-KR" : "en-US");

  return (
    <article className="flex flex-col gap-3 rounded-xl border border-outline-variant bg-surface p-5 transition-shadow hover:shadow-card-hover">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex items-center gap-2 text-body-sm">
            <span className={`rounded-sm px-1.5 py-0.5 text-label-caps uppercase ${sourceBadge}`}>
              {entry.source_db}
            </span>
            <span className="font-mono text-mono-data text-on-surface-variant">{entry.source_id}</span>
            <span className="font-mono text-mono-data text-on-surface-variant/70">· {dateStr}</span>
          </div>
          <Link
            href={`/datasets/${entry.dataset_id}`}
            className="text-headline-sm text-on-surface transition-colors hover:text-secondary"
          >
            {entry.title || (locale === "ko" ? "(제목 없음)" : "(no title)")}
          </Link>
          {(entry.modality.length > 0 || taxonNames.length > 0) ? (
            <div className="mt-1 flex flex-wrap gap-1.5 text-body-sm">
              {entry.modality.map((m) => (
                <span
                  key={m}
                  className="rounded-md bg-secondary-container/60 px-2 py-0.5 text-on-secondary-container"
                >
                  {m}
                </span>
              ))}
              {taxonNames.map((n) => (
                <span
                  key={n}
                  className="rounded-md bg-surface-container px-2 py-0.5 italic text-on-surface-variant"
                >
                  {n}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        {kind === "saved" ? (
          <button
            type="button"
            onClick={() => remove(entry.dataset_id)}
            className="shrink-0 rounded-md border border-outline-variant px-3 py-1.5 text-body-sm font-medium text-on-surface-variant transition-colors hover:border-error/40 hover:text-error"
          >
            {locale === "ko" ? "찜 해제" : "Unsave"}
          </button>
        ) : null}
      </div>
    </article>
  );
}
