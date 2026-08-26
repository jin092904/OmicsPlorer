"use client";

// 검색 결과 카드의 점수 시각화.
//
// 디자인 의도:
//   - 사용자에게는 "관련도" 한 줄 (사람이 읽기 쉬운 0~100% + 등급) 만 우선 노출.
//   - 자세히 알고 싶은 사용자만 펼쳐서 의미/단어/RRF/재순위 원시값 확인.
//   - 이전 버전은 4개 막대를 동시에 노출했는데 단위가 모두 달라 (0~1, 0~50, 0~0.05, -10~+10)
//     비교 불가능했음.
import { useState } from "react";

import type { ScoreBreakdown as ScoreBreakdownT } from "@/lib/api";
import type { T } from "@/lib/i18n";

type Locale = "ko" | "en";

// 사용자에게 보여줄 단일 "관련도" 점수 (0~1).
//
// 신호 종류:
//   - semantic (0~1, dense embedding 코사인 유사도)
//   - lexical (0~50+, BM25)
//   - rerank (cross-encoder logit, 보통 -8 ~ +5; 음수도 흔함)
//
// 단순히 rerank 만 sigmoid 로 변환하면 음수 rerank 가 우세할 때 거의 0% 로 깔린다.
// → "의미 매칭 강함(semantic≥0.7)" 칩 옆에 0% 가 뜨는 모순 발생.
// 그래서 semantic 과 rerank 를 같이 가중 평균해 baseline 을 잃지 않도록 한다.
function compositeScore(b: ScoreBreakdownT): number {
  const clamp01 = (x: number): number => Math.max(0, Math.min(1, x));
  const semPart = clamp01(b.semantic ?? 0); // 0~1 그대로
  const lex = b.lexical ?? 0;
  const lexPart = clamp01(Math.log1p(lex) / Math.log1p(30));

  if (b.rerank != null) {
    // rerank -5 → 0, +5 → 1 로 선형 매핑 (clip). sigmoid 보다 분포가 평탄해 시각적으로 spread 잘 보임.
    const rerankPart = clamp01((b.rerank + 5) / 10);
    // 50% rerank + 40% semantic + 10% lexical — rerank 가 주, semantic 이 baseline.
    return clamp01(0.5 * rerankPart + 0.4 * semPart + 0.1 * lexPart);
  }
  // rerank 없으면 sem + lex 가중평균만 사용.
  return clamp01(0.7 * semPart + 0.3 * lexPart);
}

function gradeOf(pct: number, locale: Locale): { label: string; color: string } {
  if (pct >= 70) {
    return {
      label: locale === "ko" ? "높음" : "High",
      color: "bg-secondary-container text-on-secondary-container",
    };
  }
  if (pct >= 40) {
    return {
      label: locale === "ko" ? "중간" : "Mid",
      color: "bg-tertiary-container text-on-tertiary-container",
    };
  }
  return {
    label: locale === "ko" ? "낮음" : "Low",
    color: "bg-surface-container-high text-on-surface-variant",
  };
}

function semanticLabel(sem: number | null, locale: Locale): string | null {
  if (sem == null) return null;
  if (sem >= 0.7) return locale === "ko" ? "의미 매칭 강함" : "Strong semantic";
  if (sem >= 0.5) return locale === "ko" ? "의미 매칭" : "Semantic match";
  return null;
}

function lexicalLabel(lex: number | null, locale: Locale): string | null {
  if (lex == null) return null;
  if (lex >= 10) return locale === "ko" ? "단어 매칭 강함" : "Strong keyword";
  if (lex >= 3) return locale === "ko" ? "단어 매칭" : "Keyword match";
  return null;
}

export function ScoreBreakdown({
  breakdown,
  t,
  locale,
}: {
  breakdown: ScoreBreakdownT;
  t: T;
  locale?: Locale;
}) {
  const _locale: Locale = locale ?? "ko";
  const [open, setOpen] = useState(false);
  const score = compositeScore(breakdown);
  const pct = Math.round(score * 100);
  const grade = gradeOf(pct, _locale);
  const sigSem = semanticLabel(breakdown.semantic, _locale);
  const sigLex = lexicalLabel(breakdown.lexical, _locale);

  const detailsLabel = _locale === "ko" ? "상세" : "Details";
  const relevanceLabel = _locale === "ko" ? "관련도" : "Relevance";

  return (
    <div className="flex flex-col gap-2">
      {/* 메인: 관련도 한 줄 */}
      <div className="flex items-center gap-3">
        <span className="w-14 shrink-0 text-label-caps uppercase text-on-surface-variant">
          {relevanceLabel}
        </span>
        <div
          className="relative h-2 flex-grow overflow-hidden rounded-full bg-surface-container-high"
          aria-label={`${relevanceLabel} ${pct}%`}
        >
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-secondary"
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="w-10 shrink-0 text-right font-mono text-mono-data text-on-surface">
          {pct}%
        </span>
        <span
          className={`shrink-0 rounded-md px-2 py-0.5 text-label-caps uppercase ${grade.color}`}
        >
          {grade.label}
        </span>
      </div>

      {/* 보조 신호 chip 들 (의미 매칭 / 단어 매칭) — 강한 신호만 노출 */}
      {sigSem || sigLex ? (
        <div className="flex flex-wrap gap-1.5 pl-[4.4rem]">
          {sigSem ? (
            <span className="rounded-md bg-secondary-container/60 px-2 py-0.5 text-body-sm text-on-secondary-container">
              {sigSem}
            </span>
          ) : null}
          {sigLex ? (
            <span className="rounded-md bg-tertiary-container/60 px-2 py-0.5 text-body-sm text-on-tertiary-container">
              {sigLex}
            </span>
          ) : null}
        </div>
      ) : null}

      {/* 상세 토글 — 점수 분해 원시값 */}
      <div className="pl-[4.4rem]">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-body-sm text-on-surface-variant/70 transition-colors hover:text-on-surface"
          aria-expanded={open}
        >
          {open ? "▾" : "▸"} {detailsLabel}
        </button>
      </div>

      {open ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 pl-[4.4rem] text-body-sm">
          <span className="text-on-surface-variant">{t.result.semantic}</span>
          <span className="text-right font-mono text-mono-data text-on-surface">
            {breakdown.semantic == null ? "—" : breakdown.semantic.toFixed(3)}
          </span>
          <span className="text-on-surface-variant">{t.result.lexical}</span>
          <span className="text-right font-mono text-mono-data text-on-surface">
            {breakdown.lexical == null ? "—" : breakdown.lexical.toFixed(2)}
          </span>
          <span className="text-on-surface-variant">{t.result.rrf}</span>
          <span className="text-right font-mono text-mono-data text-on-surface">
            {breakdown.rrf.toFixed(4)}
          </span>
          {breakdown.rerank != null ? (
            <>
              <span className="text-on-surface-variant">Rerank</span>
              <span className="text-right font-mono text-mono-data text-on-surface">
                {breakdown.rerank.toFixed(2)}
              </span>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
