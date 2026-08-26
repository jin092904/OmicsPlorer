"use client";

import { useEffect, useRef, useState } from "react";

import { useNavigation } from "@/components/NavigationPending";
import type { T } from "@/lib/i18n";

// 번역 완료 후 버튼 쿨타임(초). 연타로 인한 Ollama 큐 적체 + 체감 멈춤 방지.
const TRANSLATE_COOLDOWN_SEC = 3;

export function HeroSearch({
  placeholder,
  submitLabel,
  tryLabel,
  suggestions,
  tr,
}: {
  placeholder: string;
  submitLabel: string;
  tryLabel: string;
  suggestions: readonly string[];
  tr: T["translate"];
}) {
  const { navigate } = useNavigation();
  const [q, setQ] = useState("");
  const [showTranslator, setShowTranslator] = useState(false);
  const [ko, setKo] = useState("");
  const [translating, setTranslating] = useState(false);
  const [translated, setTranslated] = useState<string | null>(null);
  const [translateError, setTranslateError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  // 동기 재진입 빗장 + in-flight 요청 취소용. setTranslating 은 비동기라
  // 같은 프레임 연타를 못 막는다 → ref 로 즉시 차단.
  const inFlightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  // 쿨타임 카운트다운.
  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [cooldown]);

  const submit = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    navigate(`/search?q=${encodeURIComponent(trimmed)}`);
  };

  const onTranslate = async () => {
    const text = ko.trim();
    if (!text) return;
    // 동기 빗장 + 쿨타임 가드 — 같은 프레임 연타 / 쿨타임 중이면 즉시 반환.
    if (inFlightRef.current || cooldown > 0) return;
    inFlightRef.current = true;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setTranslating(true);
    setTranslateError(null);
    setTranslated(null);
    try {
      const resp = await fetch("/api/translate-query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, target_lang: "en" }),
        signal: controller.signal,
      });
      if (!resp.ok) {
        setTranslateError(
          resp.status === 503
            ? tr.modelDown
            : tr.httpFail.replace("{status}", String(resp.status)),
        );
        return;
      }
      const data = (await resp.json()) as { translated: string };
      setTranslated(data.translated);
      setCooldown(TRANSLATE_COOLDOWN_SEC);
    } catch (e) {
      // 취소(AbortError)는 의도된 동작 — 에러 표시 안 함.
      if (!(e instanceof DOMException && e.name === "AbortError")) {
        setTranslateError(tr.networkError);
      }
    } finally {
      inFlightRef.current = false;
      setTranslating(false);
    }
  };

  const useTranslation = () => {
    if (!translated) return;
    setQ(translated);
    submit(translated);
  };

  return (
    <div className="mx-auto w-full max-w-3xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(q);
        }}
        className="relative w-full"
      >
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={placeholder}
          autoFocus
          className="block w-full rounded-2xl border border-outline-variant bg-surface py-5 pl-6 pr-32 text-body-lg text-on-surface placeholder-on-surface-variant shadow-card transition-all hover:shadow-card-hover focus:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary/20"
        />
        <button
          type="submit"
          className="absolute inset-y-0 right-2.5 my-auto flex h-12 items-center gap-1.5 rounded-xl bg-secondary px-5 text-body-md font-medium text-on-secondary transition-colors hover:bg-secondary/90"
        >
          {submitLabel}
        </button>
      </form>

      {/* Translator toggle */}
      <div className="mt-3 flex justify-center">
        <button
          type="button"
          onClick={() => setShowTranslator((s) => !s)}
          className="inline-flex items-center gap-1.5 text-body-sm text-on-surface-variant transition-colors hover:text-on-surface"
        >
          <span aria-hidden>↗</span>
          {showTranslator ? tr.toggleClose : tr.toggleOpen}
        </button>
      </div>

      {/* Translator panel */}
      {showTranslator ? (
        <div className="mt-3 rounded-2xl border border-outline-variant bg-surface-container-low/40 p-4 shadow-card">
          <p className="mb-2 text-body-sm text-on-surface-variant">{tr.helper}</p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              type="text"
              value={ko}
              onChange={(e) => setKo(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onTranslate();
                }
              }}
              placeholder={tr.koPlaceholder}
              className="flex-1 rounded-lg border border-outline-variant bg-surface px-3 py-2 text-body-md text-on-surface focus:border-secondary focus:outline-none"
            />
            <button
              type="button"
              onClick={onTranslate}
              disabled={translating || cooldown > 0 || !ko.trim()}
              title={cooldown > 0 ? tr.cooldownHint : undefined}
              className="inline-flex h-10 items-center justify-center rounded-lg bg-secondary px-4 text-body-md font-medium text-on-secondary transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {translating
                ? tr.inProgress
                : cooldown > 0
                  ? tr.cooldownCountdown.replace("{n}", String(cooldown))
                  : tr.translateBtn}
            </button>
          </div>
          {cooldown > 0 ? (
            <p className="mt-2 text-body-sm text-on-surface-variant/70">{tr.cooldownHint}</p>
          ) : null}
          {translateError ? (
            <p className="mt-2 text-body-sm text-error">{translateError}</p>
          ) : null}
          {translated ? (
            <div className="mt-3 flex flex-col gap-2 rounded-lg border border-secondary/30 bg-secondary-container/20 p-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex-1">
                <div className="text-label-caps uppercase text-on-surface-variant">
                  {tr.englishLabel}
                </div>
                <div className="mt-1 font-medium text-on-surface">{translated}</div>
              </div>
              <button
                type="button"
                onClick={useTranslation}
                className="inline-flex h-9 items-center justify-center rounded-md bg-secondary px-3 text-body-sm font-medium text-on-secondary transition-opacity hover:opacity-90"
              >
                {tr.useThis}
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-7 flex flex-wrap items-center justify-center gap-2 text-body-sm">
        <span className="text-on-surface-variant">{tryLabel}</span>
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setQ(s);
              submit(s);
            }}
            className="rounded-full border border-outline-variant bg-surface px-3.5 py-1.5 text-on-surface-variant transition-colors hover:border-secondary hover:bg-secondary-container/40 hover:text-on-secondary-container"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
