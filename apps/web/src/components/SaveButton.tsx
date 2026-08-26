"use client";

import { useSavedDatasets, type DatasetMemoryEntry } from "@/lib/datasetMemory";

export function SaveButton({
  entry,
  locale,
  size = "md",
}: {
  entry: Omit<DatasetMemoryEntry, "ts">;
  locale: "ko" | "en";
  size?: "sm" | "md";
}) {
  const { isSaved, toggle, syncing } = useSavedDatasets();
  const saved = isSaved(entry.dataset_id);
  const label = saved
    ? locale === "ko"
      ? "찜 해제"
      : "Unsave"
    : locale === "ko"
      ? "찜"
      : "Save";
  const cls =
    size === "sm" ? "h-8 px-3 text-body-sm" : "h-9 px-3.5 text-body-sm";

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={syncing}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        if (syncing) return; // 초기 서버 동기 중 클릭 차단 — reconcile 레이스 방지(2026-07-03)
        toggle(entry);
      }}
      className={`flex shrink-0 items-center gap-1.5 rounded-md border ${cls} font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        saved
          ? "border-secondary/40 bg-secondary-container/50 text-on-secondary-container"
          : "border-outline-variant bg-surface text-on-surface-variant hover:border-on-surface-variant/40 hover:text-on-surface"
      }`}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill={saved ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z" />
      </svg>
      {label}
    </button>
  );
}
