// 다운로드 코드 스니펫 — source selector + R / Python / Bash 탭 + 복사 버튼.
//
// 데이터셋에 여러 source (GEO + SRA + ENA) 가 있으면 selector 로 선택.
// 선택된 source 의 가용 언어 탭만 표시.
"use client";

import { useMemo, useState } from "react";

import type { Snippet, SnippetsResponse, SourceSnippetGroup } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

const LANG_LABELS: Record<Snippet["language"], string> = {
  R: "R",
  python: "Python",
  bash: "Bash",
};

export function DownloadSnippets({
  data,
  locale,
}: {
  data: SnippetsResponse | null;
  locale: Locale;
}) {
  const t = (ko: string, en: string) => (locale === "ko" ? ko : en);

  // sources 가 있으면 그룹 단위 selector. 없으면 legacy snippets 만 사용.
  const sourceGroups: SourceSnippetGroup[] = useMemo(() => {
    if (data?.sources && data.sources.length > 0) return data.sources;
    if (data && data.snippets.length > 0) {
      return [{
        source_db: data.source_db,
        source_id: data.source_id,
        is_primary: true,
        snippets: data.snippets,
      }];
    }
    return [];
  }, [data]);

  const [activeSourceIdx, setActiveSourceIdx] = useState(0);
  const activeSource = sourceGroups[activeSourceIdx] ?? sourceGroups[0];

  const grouped = useMemo(() => {
    const byLang: Record<string, Snippet[]> = {};
    for (const s of activeSource?.snippets ?? []) {
      (byLang[s.language] ||= []).push(s);
    }
    return byLang;
  }, [activeSource]);

  const languages = Object.keys(grouped) as Snippet["language"][];
  const [activeLang, setActiveLang] = useState<Snippet["language"] | null>(null);
  const active = activeLang && languages.includes(activeLang) ? activeLang : languages[0];

  if (!data || sourceGroups.length === 0) {
    return (
      <div className="rounded-md border border-outline-variant bg-surface-container-low/60 px-3 py-2 text-body-sm text-on-surface-variant">
        {t(
          "이 데이터 소스에 대한 다운로드 스니펫은 아직 준비되지 않았습니다.",
          "Download snippets are not yet available for this data source.",
        )}
      </div>
    );
  }

  const items = (active && grouped[active]) || [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="text-label-caps uppercase text-on-surface-variant">
          {t("다운로드 스니펫", "Download snippets")}
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          {/* Source selector — 여러 source 가 있을 때만 노출 */}
          {sourceGroups.length > 1 ? (
            <label className="inline-flex items-center gap-2 text-body-sm text-on-surface-variant">
              <span>{t("소스", "Source")}</span>
              <select
                value={activeSourceIdx}
                onChange={(e) => {
                  setActiveSourceIdx(Number(e.target.value));
                  setActiveLang(null); // 새 source 의 첫 lang 으로
                }}
                className="rounded-md border border-outline-variant bg-surface px-2 py-1 text-body-sm text-on-surface focus:border-secondary focus:outline-none"
              >
                {sourceGroups.map((g, i) => (
                  <option key={`${g.source_db}:${g.source_id}`} value={i}>
                    {g.source_db} · {g.source_id}
                    {g.is_primary ? ` (${t("기본", "primary")})` : ""}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <div role="tablist" className="flex gap-1">
            {languages.map((lang) => (
              <button
                key={lang}
                type="button"
                role="tab"
                aria-selected={lang === active}
                onClick={() => setActiveLang(lang)}
                className={`h-7 rounded-md px-2.5 text-body-sm font-medium transition-colors ${
                  lang === active
                    ? "bg-secondary text-on-secondary"
                    : "bg-surface-container text-on-surface-variant hover:bg-surface-container-high"
                }`}
              >
                {LANG_LABELS[lang]}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {items.map((s) => (
          <SnippetCard key={`${activeSource?.source_db}:${s.title}`} snippet={s} locale={locale} />
        ))}
      </div>
    </div>
  );
}

function SnippetCard({ snippet, locale }: { snippet: Snippet; locale: Locale }) {
  const [copied, setCopied] = useState(false);
  const t = (ko: string, en: string) => (locale === "ko" ? ko : en);

  async function copy() {
    try {
      await navigator.clipboard.writeText(snippet.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // graceful fail
    }
  }

  return (
    <article className="rounded-md border border-outline-variant bg-surface-container-low/40">
      <header className="flex items-start justify-between gap-3 border-b border-outline-variant px-3 py-2">
        <div className="min-w-0">
          <h4 className="truncate text-body-md font-medium text-on-surface">{snippet.title}</h4>
          <p className="mt-0.5 text-body-sm text-on-surface-variant">{snippet.description}</p>
        </div>
        <button
          type="button"
          onClick={copy}
          className="h-7 shrink-0 rounded-md bg-surface-container px-2.5 text-body-sm font-medium text-on-surface transition-colors hover:bg-surface-container-high"
        >
          {copied ? t("복사됨", "Copied") : t("복사", "Copy")}
        </button>
      </header>
      <pre className="overflow-x-auto bg-surface-container-low/80 px-3 py-3 font-mono text-mono-data text-on-surface">
        <code>{snippet.code}</code>
      </pre>
      {snippet.requires.length > 0 ? (
        <footer className="border-t border-outline-variant px-3 py-2 text-body-sm text-on-surface-variant">
          <span className="text-label-caps uppercase">{t("필요", "Requires")}</span>{" "}
          {snippet.requires.join(" · ")}
        </footer>
      ) : null}
    </article>
  );
}
