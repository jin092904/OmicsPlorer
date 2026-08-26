"use client";

// 클라이언트 사이드바 상태 — 쿠키 영속 + 같은 탭 내 다른 컴포넌트 동기화 (custom event).
// 서버는 layout.tsx 에서 getSidebarState() 로 SSR 시 hydrate 되도록 초기 prop 으로 전달.
import { useCallback, useEffect, useState } from "react";

import { isSidebarState, SIDEBAR_COOKIE, type SidebarState } from "./sidebar";

const CHANGE_EVENT = "genofinder:sidebar-change";

function readCookie(): SidebarState | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(new RegExp(`(?:^|; )${SIDEBAR_COOKIE}=([^;]+)`));
  if (!m) return null;
  const v = decodeURIComponent(m[1] ?? "");
  return isSidebarState(v) ? v : null;
}

function writeCookie(state: SidebarState): void {
  document.cookie = `${SIDEBAR_COOKIE}=${state}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

export function useSidebar(initial: SidebarState): {
  state: SidebarState;
  collapsed: boolean;
  toggle: () => void;
  setState: (s: SidebarState) => void;
} {
  const [state, setStateRaw] = useState<SidebarState>(initial);

  useEffect(() => {
    const fromCookie = readCookie();
    if (fromCookie && fromCookie !== state) setStateRaw(fromCookie);
    const handler = () => {
      const v = readCookie();
      if (v) setStateRaw(v);
    };
    window.addEventListener(CHANGE_EVENT, handler);
    return () => window.removeEventListener(CHANGE_EVENT, handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setState = useCallback((s: SidebarState) => {
    writeCookie(s);
    setStateRaw(s);
  }, []);

  const toggle = useCallback(() => {
    const next = state === "expanded" ? "collapsed" : "expanded";
    writeCookie(next);
    setStateRaw(next);
  }, [state]);

  return { state, collapsed: state === "collapsed", toggle, setState };
}
