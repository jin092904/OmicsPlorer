"use client";

// 클라이언트 테마 훅 — 쿠키에 저장 (서버/SSR 도 동일 값을 본다) + system 변경 감지.
// 초기 적용은 ThemeScript (head 인라인) 가 처리 — 본 훅은 변경 시 갱신만 담당.
import { useCallback, useEffect, useState } from "react";

import { isTheme, THEME_COOKIE, type Theme } from "./theme";

function readCookie(): Theme {
  if (typeof document === "undefined") return "system";
  const m = document.cookie.match(new RegExp(`(?:^|; )${THEME_COOKIE}=([^;]+)`));
  if (!m) return "system";
  const v = decodeURIComponent(m[1] ?? "");
  return isTheme(v) ? v : "system";
}

function writeCookie(theme: Theme): void {
  document.cookie = `${THEME_COOKIE}=${theme}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
}

function applyToHtml(theme: Theme): void {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
}

export function useTheme(): {
  theme: Theme;
  setTheme: (t: Theme) => void;
  isDark: boolean;
} {
  const [theme, setThemeState] = useState<Theme>("system");
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    const current = readCookie();
    setThemeState(current);
    applyToHtml(current);
    setIsDark(document.documentElement.classList.contains("dark"));

    // system 모드일 때만 OS 변경에 반응.
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handle = () => {
      if (readCookie() === "system") {
        applyToHtml("system");
        setIsDark(document.documentElement.classList.contains("dark"));
      }
    };
    mq.addEventListener("change", handle);
    return () => mq.removeEventListener("change", handle);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    writeCookie(t);
    applyToHtml(t);
    setThemeState(t);
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  return { theme, setTheme, isDark };
}
