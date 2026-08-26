"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  useTransition,
} from "react";

// ---------------------------------------------------------------------------
// 전역 네비게이션 Pending 컨텍스트 (loading state).
//
// 문제: /search 는 서버 컴포넌트라 URL(searchParams)이 바뀌면 서버에서 다시
// 렌더된다. 그런데 Next.js 의 loading.tsx 는 "같은 라우트에서 searchParams 만
// 바뀌는 재검색"에는 다시 뜨지 않는다(라우트 세그먼트 재사용). 그래서 결과가
// 이미 떠 있는 화면에서 다른 검색어로 검색하면 "로딩 중"임을 알 수 없었다.
//
// 해법: router.push 를 React useTransition 으로 감싼다. isPending 은 새 페이지의
// 서버 렌더가 끝나 화면에 커밋될 때까지 true 로 유지된다 → 진짜 "진행 중" 신호.
// (기존 NavigationProgress 는 useEffect 가 렌더 "완료 후"에 발동해 늦게 떴음 → 대체.)
//
// Provider 를 root layout 에 두는 이유: 페이지 전환 중에도 안 사라지는 유일한
// 지점이라 isPending 이 전환 내내 안정적으로 유지된다(AppShell 은 페이지마다 새로
// 생성되므로 부적합).
// ---------------------------------------------------------------------------

type NavigateOptions = { replace?: boolean };
type NavigationPendingValue = {
  isPending: boolean;
  /** router.push/replace 를 transition 으로 감싸 진행 상태를 추적하며 이동한다. */
  navigate: (href: Route, opts?: NavigateOptions) => void;
  /** router.refresh() 를 transition 으로 감싼다(예: 언어 전환 시 로딩 표시). */
  refresh: () => void;
};

const NavigationPendingContext = createContext<NavigationPendingValue | null>(null);

export function useNavigation(): NavigationPendingValue {
  const ctx = useContext(NavigationPendingContext);
  if (!ctx) {
    throw new Error("useNavigation must be used within NavigationPendingProvider");
  }
  return ctx;
}

export function NavigationPendingProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const navigate = useCallback(
    (href: Route, opts?: NavigateOptions) => {
      startTransition(() => {
        if (opts?.replace) router.replace(href);
        else router.push(href);
      });
    },
    [router],
  );

  const refresh = useCallback(() => {
    startTransition(() => {
      router.refresh();
    });
  }, [router]);

  return (
    <NavigationPendingContext.Provider value={{ isPending, navigate, refresh }}>
      <NavigationProgressBar active={isPending} />
      {children}
    </NavigationPendingContext.Provider>
  );
}

// 상단 진행 바 — 실제 isPending 동안에만 흐른다(전환 중에 즉시 보이고, 완료되면 채워지며 사라짐).
function NavigationProgressBar({ active }: { active: boolean }) {
  const [progress, setProgress] = useState(0);
  const [visible, setVisible] = useState(false);
  const wasActive = useRef(false);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fadeRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (active) {
      wasActive.current = true;
      if (fadeRef.current) {
        clearTimeout(fadeRef.current);
        fadeRef.current = null;
      }
      setVisible(true);
      setProgress((p) => (p < 12 ? 12 : p));
      tickRef.current = setInterval(() => {
        // 90% 까지 점점 느리게 차오르다 멈춰서 실제 완료 신호를 기다림(NProgress 패턴).
        setProgress((p) => (p < 90 ? p + (90 - p) * 0.12 : p));
      }, 120);
      return () => {
        if (tickRef.current) {
          clearInterval(tickRef.current);
          tickRef.current = null;
        }
      };
    }
    // active=false: 처음 마운트(한 번도 시작 안 함)면 아무것도 안 함.
    if (!wasActive.current) return;
    wasActive.current = false;
    setProgress(100);
    fadeRef.current = setTimeout(() => {
      setVisible(false);
      setProgress(0);
    }, 240);
    return () => {
      if (fadeRef.current) {
        clearTimeout(fadeRef.current);
        fadeRef.current = null;
      }
    };
  }, [active]);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-[120] h-1">
      <div
        className="h-full rounded-r-full bg-secondary shadow-[0_0_8px_rgba(20,184,166,0.7)] transition-[width,opacity] duration-200 ease-out"
        style={{ width: `${progress}%`, opacity: visible ? 1 : 0 }}
      />
    </div>
  );
}

// 검색 결과 영역 위에 덮는 가벼운 로딩 오버레이.
// 결과가 이미 떠 있는 상태에서 재검색할 때, 기존 결과를 살짝 흐리게 + "검색 중…" 칩으로
// 진행 중임을 분명히 보여준다. 부모 컨테이너에 relative 가 있어야 한다.
export function SearchPendingOverlay({ locale }: { locale: "ko" | "en" }) {
  const { isPending } = useNavigation();
  if (!isPending) return null;
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={locale === "ko" ? "검색 중" : "Searching"}
      className="pointer-events-none absolute inset-0 z-30 flex justify-center bg-background/45 backdrop-blur-[1px]"
    >
      <div className="mt-12 flex h-fit items-center gap-2.5 rounded-full border border-outline-variant bg-surface px-4 py-2 text-body-sm font-medium text-on-surface shadow-card">
        <span
          aria-hidden
          className="h-4 w-4 animate-spin rounded-full border-2 border-secondary border-t-transparent"
        />
        {locale === "ko" ? "검색 중…" : "Searching…"}
      </div>
    </div>
  );
}
