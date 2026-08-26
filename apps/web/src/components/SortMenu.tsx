"use client";

// 검색 결과 정렬 드롭다운. URL `sort` query string 으로 동작 → 서버 컴포넌트가 읽음.
import { useSearchParams } from "next/navigation";

import { useNavigation } from "@/components/NavigationPending";
import type { SortMode } from "@/lib/api";

type Props = {
  current: SortMode;
  locale: "ko" | "en";
};

const OPTIONS_KO: { value: SortMode; label: string }[] = [
  { value: "relevance", label: "관련도 순" },
  { value: "n_samples_desc", label: "표본 수 많은 순" },
  { value: "submission_date_desc", label: "최신 순" },
  { value: "submission_date_asc", label: "오래된 순" },
];
const OPTIONS_EN: { value: SortMode; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "n_samples_desc", label: "Most samples" },
  { value: "submission_date_desc", label: "Newest first" },
  { value: "submission_date_asc", label: "Oldest first" },
];

export function SortMenu({ current, locale }: Props) {
  const { navigate } = useNavigation();
  const params = useSearchParams();
  const options = locale === "ko" ? OPTIONS_KO : OPTIONS_EN;

  function onChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const next = new URLSearchParams(params.toString());
    if (e.target.value === "relevance") {
      next.delete("sort");
    } else {
      next.set("sort", e.target.value);
    }
    // 정렬 변경 시 1페이지로 리셋
    next.delete("page");
    navigate(`/search?${next.toString()}`);
  }

  return (
    <label className="inline-flex items-center gap-2 text-body-sm text-on-surface-variant">
      <span className="font-medium">{locale === "ko" ? "정렬" : "Sort"}</span>
      <select
        value={current}
        onChange={onChange}
        className="rounded-md border border-outline-variant bg-surface px-2 py-1 text-body-sm text-on-surface focus:border-secondary focus:outline-none"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
