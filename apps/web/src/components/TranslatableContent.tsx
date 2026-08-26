// 한국어 모드에서만 보이는 "번역" 토글. RSC 안전한 Context 패턴.
//
// 구조:
//   - <TranslateProvider> : 클라이언트, dataset_id + 원문 + 번역 state. 부모는 server.
//   - <TranslateToggleButton> : 버튼 (locale=ko 일 때만 표시)
//   - <TranslatableTitle original=...> : 원문 prop 으로 받고, state 켜져 있으면 번역본 표시
//   - <TranslatableAbstract original=...> : 동일
//
// page.tsx (server) 에서는 단순히 컴포넌트들을 그대로 배치하면 됨. 함수 prop / render prop 없음.
"use client";

import {
  ReactNode,
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

import type { Translation } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

type Ctx = {
  datasetId: string;
  locale: Locale;
  showTranslated: boolean;
  title: string | null;
  abstract: string | null;
  anyTranslated: boolean; // 실제로 번역된 필드가 하나라도 있나(원문 fallback 과 구분)
  pending: boolean;
  error: string | null;
  cooldown: number; // >0 이면 N초 쿨타임 중 (버튼 잠금 + 카운트다운 표시)
  toggle: () => Promise<void>;
};

// 완료 후 버튼 쿨타임(초). 연타로 인한 Ollama 큐 적체 + 체감 멈춤 방지.
const TRANSLATE_COOLDOWN_SEC = 3;

const TranslateCtx = createContext<Ctx | null>(null);

export function TranslateProvider({
  datasetId,
  locale,
  originalTitle,
  originalAbstract,
  children,
}: {
  datasetId: string;
  locale: Locale;
  originalTitle: string | null;
  originalAbstract: string | null;
  children: ReactNode;
}) {
  const [translated, setTranslated] = useState<{
    title: string | null;
    abstract: string | null;
  } | null>(null);
  const [showTranslated, setShowTranslated] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  // 동기 재진입 빗장: setPending 은 비동기라 같은 프레임 연타 시 disabled 가 안 먹는다.
  // ref 는 즉시 반영되므로 fetch 호출 전 동기적으로 막는다.
  const inFlightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  // 언마운트 시 in-flight 요청 취소.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // 쿨타임 카운트다운 — cooldown>0 동안 1초씩 감소.
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [cooldown]);

  async function toggle() {
    setError(null);
    if (showTranslated) {
      setShowTranslated(false);
      return;
    }
    if (translated) {
      setShowTranslated(true);
      return;
    }
    // 동기 빗장 + 쿨타임 가드 — 둘 중 하나라도 걸리면 즉시 반환.
    if (inFlightRef.current || cooldown > 0) return;
    inFlightRef.current = true;
    // 혹시 이전 요청이 남아 있으면 취소(방어).
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPending(true);
    try {
      const resp = await fetch(
        `/api/translate?id=${encodeURIComponent(datasetId)}&lang=ko`,
        { method: "POST", signal: controller.signal },
      );
      if (!resp.ok) {
        setError("번역 실패 — 잠시 후 재시도");
        return;
      }
      const data = (await resp.json()) as Translation;
      // null 보존(원문 fallback 과 구분) — 표시 단계에서 ?? original 처리.
      setTranslated({ title: data.title, abstract: data.abstract });
      setShowTranslated(true);
      setCooldown(TRANSLATE_COOLDOWN_SEC);
    } catch (e) {
      // 취소(AbortError)는 의도된 동작이므로 에러로 표시하지 않는다.
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setError("네트워크 오류");
      }
    } finally {
      inFlightRef.current = false;
      setPending(false);
    }
  }

  const value: Ctx = {
    datasetId,
    locale,
    showTranslated,
    title:
      showTranslated && translated ? (translated.title ?? originalTitle) : originalTitle,
    abstract:
      showTranslated && translated ? (translated.abstract ?? originalAbstract) : originalAbstract,
    anyTranslated: translated != null && (translated.title != null || translated.abstract != null),
    pending,
    error,
    cooldown,
    toggle,
  };

  return <TranslateCtx.Provider value={value}>{children}</TranslateCtx.Provider>;
}

function useTranslate(): Ctx {
  const ctx = useContext(TranslateCtx);
  if (ctx === null) {
    throw new Error(
      "useTranslate must be used inside <TranslateProvider>",
    );
  }
  return ctx;
}

export function TranslatableTitle({
  original,
  fallback,
  className,
}: {
  original: string | null;
  fallback: string;
  className?: string;
}) {
  const { title } = useTranslate();
  const display = title ?? original;
  return <h1 className={className}>{display || fallback}</h1>;
}

export function TranslatableAbstract({
  original,
  emptyText,
  className,
  emptyClassName,
}: {
  original: string | null;
  emptyText: string;
  className?: string;
  emptyClassName?: string;
}) {
  const { abstract } = useTranslate();
  const display = abstract ?? original;
  if (!display) {
    return <p className={emptyClassName}>{emptyText}</p>;
  }
  return <p className={className}>{display}</p>;
}

export function TranslateToggleButton() {
  const { locale, showTranslated, anyTranslated, pending, error, cooldown, toggle } =
    useTranslate();
  if (locale !== "ko") return null;
  const locked = pending || cooldown > 0;
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={toggle}
        disabled={locked}
        aria-pressed={showTranslated}
        title={cooldown > 0 ? "너무 연속으로 누르지 마세요" : undefined}
        className={`h-7 rounded-md px-2.5 text-body-sm font-medium transition-colors disabled:opacity-50 ${
          showTranslated
            ? "bg-secondary text-on-secondary"
            : "border border-outline-variant bg-surface-container text-on-surface-variant hover:bg-surface-container-high"
        }`}
      >
        {pending
          ? "번역 중… (5-30초)"
          : cooldown > 0
            ? `잠시만요… ${cooldown}초`
            : showTranslated
              ? "원문 보기"
              : "한국어로 번역"}
      </button>
      {error ? <span className="text-body-sm text-error">{error}</span> : null}
      {cooldown > 0 ? (
        <span className="text-body-sm text-on-surface-variant/70">
          너무 연속으로 누르지 마세요
        </span>
      ) : showTranslated ? (
        <span className="text-body-sm text-on-surface-variant/70">
          {anyTranslated ? "자동 번역" : "원문 (번역 결과 없음)"}
        </span>
      ) : null}
    </div>
  );
}
