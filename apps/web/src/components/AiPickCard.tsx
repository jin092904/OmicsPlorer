// AI's Pick (project_ai_pick_feature.md) — 검색 결과 상단의 AI 엄선 카드.
//
// 왜 client island 인가:
//   search/page.tsx 는 async Server Component 라 결과를 서버에서 즉시 렌더한다.
//   AiPickCard 는 그 렌더를 막으면 안 되므로 작은 "use client" 컴포넌트로 들어가
//   사용자가 요청할 때만 /api/ai-pick 를 fetch 한다. 검색 결과를 모델 호출 때문에
//   지연시키지 않는다. 서버 컴포넌트는 직렬화 가능한 plain props (query/filters/locale) 만 넘긴다.
//
// 영속성: 백엔드가 query+filters 해시로 24h 캐싱하므로, 같은 검색에서 다시 생성을
//   요청하면 CACHE HIT → 즉답 (cached:true). 별도 클라이언트 상태는 필요 없다.
//
// 이 기능은 선택 사항이다. 추천이 없거나 일시 오류가 나도 검색 결과 자체에는 영향을 주지 않는다.
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { AIPickItem, AIPickResponse, SearchRequest } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { translations } from "@/lib/i18n";

type Status = "idle" | "loading" | "ready" | "empty" | "error";

const SOURCE_BADGE_CLASS: Record<string, string> = {
  GEO: "bg-tertiary-container text-on-tertiary-container",
  SRA: "bg-secondary-container text-on-secondary-container",
  HCA: "bg-error-container text-on-error-container",
  GDC: "bg-primary-container text-on-primary-container",
  ENA: "bg-surface-container-high text-on-surface-variant",
};

export function AiPickCard({
  query,
  filters,
  locale,
}: {
  query: string;
  filters: Partial<SearchRequest>;
  locale: Locale;
}) {
  const requestKey = `${query}\u0000${JSON.stringify(filters)}\u0000${locale}`;
  return <AiPickCardContent key={requestKey} query={query} filters={filters} locale={locale} />;
}

function AiPickCardContent({
  query,
  filters,
  locale,
}: {
  query: string;
  filters: Partial<SearchRequest>;
  locale: Locale;
}) {
  const tr = translations[locale].aiPick;
  const t = (ko: string, en: string) => (locale === "ko" ? ko : en);

  const [picks, setPicks] = useState<AIPickItem[] | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [refreshing, setRefreshing] = useState(false);

  // filters 객체는 매 렌더 새 참조라 effect/콜백 deps 에 직접 못 쓴다 → 안정 문자열로.
  const filtersKey = JSON.stringify(filters);
  // 진행 중 요청 — 새 요청/언마운트 시 abort 해 stale 응답이 최신을 덮어쓰지 않게(latest-wins).
  const abortRef = useRef<AbortController | null>(null);

  const fetchPicks = useCallback(
    async (nocache: boolean) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      // 콜드 gemma 는 정상적으로 ~30-90초 걸린다. 그래도 진짜 멈춤(hang)이 무한 스켈레톤이
      // 되지 않게 115초 타임아웃 → TimeoutError(≠AbortError) 는 에러 카드(재시도)로 떨어진다.
      let signal: AbortSignal = ctrl.signal;
      try {
        if (typeof AbortSignal !== "undefined" && "timeout" in AbortSignal && "any" in AbortSignal) {
          signal = AbortSignal.any([ctrl.signal, AbortSignal.timeout(115_000)]);
        }
      } catch {
        signal = ctrl.signal;
      }
      const url = `/api/ai-pick${nocache ? "?nocache=1" : ""}`;
      const body = JSON.stringify({ query_text: query, ...filters, lang: locale });
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          signal,
        });
        if (ctrl.signal.aborted) return;  // 더 새 요청이 시작됨 → 이 응답 폐기
        if (!resp.ok) {
          setStatus("error");
          return;
        }
        const data = (await resp.json()) as AIPickResponse;
        if (ctrl.signal.aborted) return;
        if (!data.picks || data.picks.length === 0) {
          setPicks([]);
          setStatus("empty");
          return;
        }
        setPicks(data.picks);
        setStatus("ready");
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;  // 의도된 취소 — 무시
        setStatus("error");
      }
    },
    // filters 는 filtersKey 로 안정화. locale 바뀌면 reason 언어 갱신 위해 refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [query, filtersKey, locale],
  );

  // 언마운트 시 진행 중 요청 취소.
  useEffect(() => () => abortRef.current?.abort(), []);

  const generate = useCallback(() => {
    setStatus("loading");
    void fetchPicks(false);
  }, [fetchPicks]);

  const refresh = useCallback(async () => {
    setStatus("loading");
    setRefreshing(true);
    await fetchPicks(true);
    setRefreshing(false);
  }, [fetchPicks]);

  if (status === "idle") {
    return (
      <section
        aria-label={tr.title}
        className="flex items-center justify-between gap-3 rounded-xl border border-outline-variant bg-surface-container-low/40 px-4 py-3"
      >
        <div>
          <h2 className="text-body-md font-semibold text-on-surface">{tr.title}</h2>
          <p className="text-body-sm text-on-surface-variant">{tr.subtitle}</p>
        </div>
        <button
          type="button"
          onClick={generate}
          className="shrink-0 rounded-md border border-outline-variant px-3 py-1.5 text-body-sm font-medium text-on-surface transition-colors hover:bg-surface-container"
        >
          {tr.generate}
        </button>
      </section>
    );
  }

  // 빈 결과(추천할 게 없음): 카드를 숨기는 대신 한 줄 안내(이전엔 로딩 후 사라져 "버그처럼" 보였음).
  if (status === "empty") {
    return (
      <section
        aria-label={tr.title}
        className="rounded-lg border border-outline-variant bg-surface-container-low/30 px-4 py-2.5 text-body-sm text-on-surface-variant"
      >
        <span className="font-medium text-on-surface">{tr.title}</span>
        {" — "}
        {t("이 검색에선 뚜렷이 추천할 데이터셋을 찾지 못했어요.", "no standout picks for this search.")}
      </section>
    );
  }
  // 에러(네트워크/서버 일시 오류)는 숨기지 않고 재시도 버튼을 제공 (전엔 조용히 사라져 재시도 불가).
  if (status === "error") {
    return (
      <section
        aria-label={tr.title}
        className="flex items-center justify-between gap-3 rounded-xl border border-outline-variant bg-surface-container/30 px-4 py-3 text-body-sm text-on-surface-variant"
      >
        <span>{tr.title} — {t("불러오기 실패", "couldn't load")}</span>
        <button
          type="button"
          onClick={refresh}
          disabled={refreshing}
          className="rounded-md border border-outline-variant px-3 py-1 font-medium transition-colors hover:text-on-surface disabled:opacity-50"
        >
          {refreshing ? tr.loading : tr.refresh}
        </button>
      </section>
    );
  }

  return (
    <section
      aria-label={tr.title}
      className="rounded-xl border border-outline-variant border-l-2 border-l-secondary bg-surface-container-low/40 p-4"
    >
      <header className="mb-3 flex items-end justify-between gap-3">
        <div>
          <h2 className="text-headline-sm font-semibold text-on-surface">{tr.title}</h2>
          <p className="text-body-sm text-on-surface-variant">{tr.subtitle}</p>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={status === "loading" || refreshing}
          aria-label={tr.refresh}
          title={tr.refresh}
          className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-outline-variant px-2.5 text-body-sm text-on-surface-variant transition-colors hover:text-on-surface disabled:opacity-50"
        >
          <span aria-hidden className={refreshing ? "inline-block animate-spin" : "inline-block"}>
            ↻
          </span>
          <span className="hidden sm:inline">{tr.refresh}</span>
        </button>
      </header>

      {status === "loading" ? (
        <div>
          <p className="mb-2 inline-flex items-center gap-1.5 text-body-sm text-on-surface-variant">
            <span aria-hidden className="inline-block h-2 w-2 animate-pulse rounded-full bg-secondary" />
            {tr.loading}
          </p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="rounded-lg border border-outline-variant bg-surface p-3"
              >
                <div className="h-4 w-3/4 animate-pulse rounded bg-surface-container-high/60" />
                <div className="mt-2 h-3 w-1/3 animate-pulse rounded bg-surface-container-high/60" />
                <div className="mt-3 h-5 w-full animate-pulse rounded bg-surface-container-high/60" />
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {status === "ready" && picks ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {picks.map((p, i) => {
            const badge =
              SOURCE_BADGE_CLASS[p.source_db] ??
              "bg-surface-container-high text-on-surface-variant";
            return (
              <article
                key={p.dataset_id}
                className="flex flex-col rounded-lg border border-outline-variant bg-surface p-3 transition-shadow hover:shadow-sm"
              >
                <div className="mb-1 flex items-center gap-2">
                  <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-secondary text-label-caps font-semibold text-on-secondary">
                    {i + 1}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-label-caps font-medium ${badge}`}
                  >
                    {p.source_db} · {p.source_id}
                  </span>
                </div>

                <a
                  href={`/datasets/${p.dataset_id}`}
                  className="line-clamp-2 text-body-md font-medium text-on-surface hover:text-secondary hover:underline"
                >
                  {p.title ?? t("(제목 없음)", "(no title)")}
                </a>

                <p className="mt-2 border-l-2 border-secondary/40 pl-2 text-body-sm leading-snug text-on-surface-variant">
                  {p.reason}
                </p>

                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-label-caps text-on-surface-variant">
                  {p.n_samples != null ? (
                    <span className="rounded bg-surface-container px-1.5 py-0.5 font-mono">
                      N={p.n_samples}
                    </span>
                  ) : null}
                  {p.modality.slice(0, 2).map((m) => (
                    <span key={m} className="rounded bg-surface-container px-1.5 py-0.5">
                      {m}
                    </span>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
