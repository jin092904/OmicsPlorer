"use client";

import { useTheme } from "@/lib/useTheme";

// 헤더 아이콘 토글 — light → dark → system 순환.
export function ThemeToggle({ locale }: { locale: "ko" | "en" }) {
  const { theme, setTheme, isDark } = useTheme();
  const next = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";

  const ariaLabel =
    locale === "ko"
      ? `테마: ${labelOf(theme, "ko")} (클릭 시 ${labelOf(next, "ko")})`
      : `Theme: ${labelOf(theme, "en")} (click for ${labelOf(next, "en")})`;

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      aria-label={ariaLabel}
      title={ariaLabel}
      className="flex h-9 w-9 items-center justify-center rounded-md border border-outline-variant bg-surface text-on-surface-variant transition-colors hover:border-on-surface-variant/50 hover:text-on-surface"
    >
      {theme === "system" ? <SystemIcon /> : isDark ? <MoonIcon /> : <SunIcon />}
    </button>
  );
}

function labelOf(t: "light" | "dark" | "system", l: "ko" | "en") {
  if (l === "ko") return t === "light" ? "밝음" : t === "dark" ? "어두움" : "시스템";
  return t === "light" ? "Light" : t === "dark" ? "Dark" : "System";
}

function SunIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}
function MoonIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}
function SystemIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}
