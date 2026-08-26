"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

// 검색 자동번역(비영어→영어) on/off 토글. 쿠키 `auto_translate`(기본 OFF).
// 영어 검색 권장 방침에 따라 opt-in — 켜면 비영어 쿼리를 영어로 자동번역해 검색.
export function AutoTranslateToggle({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const [pending, start] = useTransition();

  const toggle = () => {
    const next = !enabled;
    document.cookie = `auto_translate=${next ? "1" : "0"}; path=/; max-age=${
      60 * 60 * 24 * 365
    }; SameSite=Lax`;
    start(() => router.refresh());
  };

  return (
    <div className="flex items-center gap-2 text-body-sm">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Auto-translate non-English queries to English"
        onClick={toggle}
        disabled={pending}
        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-secondary/40 focus-visible:ring-offset-2 ${
          enabled ? "bg-secondary" : "bg-outline-variant"
        } ${pending ? "opacity-60" : ""}`}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
            enabled ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
      <span className="text-on-surface-variant">Auto-translate non-English queries</span>
    </div>
  );
}
