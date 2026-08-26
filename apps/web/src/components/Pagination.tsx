"use client";

import { useSearchParams } from "next/navigation";

import { useNavigation } from "@/components/NavigationPending";

export function Pagination({
  page,
  pageSize,
  total,
  locale,
}: {
  page: number;
  pageSize: number;
  total: number;
  locale: "ko" | "en";
}) {
  const { navigate: go } = useNavigation();
  const searchParams = useSearchParams();
  // `total` 은 이제 servable_total(실제 서빙 가능한 결과 수 = dense+lexical 병합 union).
  // 그래서 그 수만큼만 페이지를 만들면 빈 페이지가 안 나온다. 방어적 상한(폭주 방지)만 유지.
  const HARD_CAP = 500;
  const totalPages = Math.min(Math.max(1, Math.ceil(total / pageSize)), HARD_CAP);

  if (totalPages <= 1) return null;

  const navigate = (target: number) => {
    const params = new URLSearchParams(searchParams);
    if (target === 1) params.delete("page");
    else params.set("page", String(target));
    go(`/search?${params.toString()}`);
  };

  const labels =
    locale === "ko"
      ? { prev: "이전", next: "다음", page: "페이지" }
      : { prev: "Prev", next: "Next", page: "Page" };

  return (
    <nav className="mt-2 flex items-center justify-between gap-3 border-t border-outline-variant pt-5 text-body-sm">
      <button
        type="button"
        onClick={() => navigate(page - 1)}
        disabled={page <= 1}
        className="rounded-md border border-outline-variant px-4 py-2 font-medium text-on-surface-variant transition-colors hover:border-on-surface-variant/50 hover:text-on-surface disabled:cursor-not-allowed disabled:opacity-40"
      >
        ← {labels.prev}
      </button>
      <span className="font-mono text-on-surface-variant">
        {labels.page} <span className="text-on-surface">{page}</span> / {totalPages}
      </span>
      <button
        type="button"
        onClick={() => navigate(page + 1)}
        disabled={page >= totalPages}
        className="rounded-md border border-outline-variant px-4 py-2 font-medium text-on-surface-variant transition-colors hover:border-on-surface-variant/50 hover:text-on-surface disabled:cursor-not-allowed disabled:opacity-40"
      >
        {labels.next} →
      </button>
    </nav>
  );
}
