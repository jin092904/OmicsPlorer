"use client";

import { useEffect, useState } from "react";

import { useNavigation } from "@/components/NavigationPending";

export function TopSearchInput({
  initialQuery = "",
  placeholder,
}: {
  initialQuery?: string;
  placeholder: string;
}) {
  const { navigate } = useNavigation();
  const [q, setQ] = useState(initialQuery);
  // 뒤로/앞으로 네비게이션 시 URL 쿼리(initialQuery)가 바뀌면 입력창도 동기화(stale 방지, 2026-07-03).
  useEffect(() => {
    setQ(initialQuery);
  }, [initialQuery]);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const trimmed = q.trim();
        if (!trimmed) return;
        navigate(`/search?${new URLSearchParams({ q: trimmed }).toString()}`);
      }}
      className="relative flex items-center"
    >
      <input
        type="text"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="h-9 w-72 rounded-full border border-outline-variant bg-surface-container-low pl-4 pr-10 text-body-sm text-on-surface placeholder-on-surface-variant transition-colors focus:border-secondary focus:bg-surface focus:outline-none focus:ring-2 focus:ring-secondary/20 lg:w-96"
      />
      <button
        type="submit"
        aria-label="search"
        className="absolute right-1.5 flex h-7 w-7 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-secondary"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12h14M13 5l7 7-7 7" />
        </svg>
      </button>
    </form>
  );
}
