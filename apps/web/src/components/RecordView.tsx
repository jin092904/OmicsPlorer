"use client";

import { useEffect } from "react";

import { useRecentlyViewed, type DatasetMemoryEntry } from "@/lib/datasetMemory";

// Server-rendered detail page 가 mount 시 한 번 호출 — 최근 본 목록에 기록.
export function RecordView({ entry }: { entry: Omit<DatasetMemoryEntry, "ts"> }) {
  const { record } = useRecentlyViewed();
  useEffect(() => {
    record(entry);
    // dataset_id 가 같으면 다시 기록하지 않음 — record() 가 dedup 함.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.dataset_id]);
  return null;
}
