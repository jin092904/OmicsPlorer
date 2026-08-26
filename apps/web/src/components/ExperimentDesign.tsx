// 실험군 / 대조군 도식 — 그룹 카드 그리드. LLM 으로 추출한 cohort_design 을 표시.
//
// design === null 인 경우:
//   - extraction 미실시 상태 → "분석 중" + "지금 분석하기" 버튼 (POST /cohort/extract 트리거)
//   - 본 컴포넌트는 server component 라 버튼만 placeholder, 실제 동작은 클라이언트 wrapper 가 처리.
"use client";

import { useState } from "react";

import type { CohortView } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

type Design = NonNullable<CohortView["design"]>;
type Group = Design["groups"][number];

const ROLE_STYLES: Record<Group["role"], string> = {
  case: "bg-error-container/40 text-on-error-container border-error/30",
  control: "bg-surface-container text-on-surface-variant border-outline-variant",
  treatment: "bg-tertiary-container/50 text-on-tertiary-container border-tertiary/30",
  comparison: "bg-secondary-container/40 text-on-secondary-container border-secondary/30",
  other: "bg-surface-container-low text-on-surface border-outline-variant",
};

function roleLabel(role: Group["role"], locale: Locale): string {
  if (locale === "ko") {
    return {
      case: "환자/케이스",
      control: "대조군",
      treatment: "처치군",
      comparison: "비교군",
      other: "기타",
    }[role];
  }
  return role;
}

function designTypeLabel(type: string, locale: Locale): string {
  if (locale === "ko") {
    return (
      {
        case_control: "환자-대조 (case-control)",
        cohort: "코호트 (cohort)",
        cross_sectional: "단면연구",
        rct: "RCT",
        time_series: "시계열",
        unknown: "유형 불명",
      } as Record<string, string>
    )[type] ?? type;
  }
  return type.replace("_", " ");
}

export function ExperimentDesign({
  design,
  datasetId,
  locale,
}: {
  design: CohortView["design"];
  datasetId: string;
  locale: Locale;
}) {
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<CohortView["design"]>(design);
  const [error, setError] = useState<string | null>(null);

  async function trigger() {
    setPending(true);
    setError(null);
    try {
      const resp = await fetch(`/api/cohort-extract?id=${encodeURIComponent(datasetId)}`, {
        method: "POST",
      });
      if (!resp.ok) {
        setError(locale === "ko" ? "분석 실패 — 잠시 후 재시도" : "Extraction failed — try again");
        return;
      }
      const data = (await resp.json()) as CohortView;
      setResult(data.design);
    } catch {
      setError(locale === "ko" ? "네트워크 오류" : "Network error");
    } finally {
      setPending(false);
    }
  }

  const t = (ko: string, en: string) => (locale === "ko" ? ko : en);

  if (result === null) {
    return (
      <div className="rounded-md border border-dashed border-outline-variant bg-surface-container-low/40 p-4 text-body-sm">
        <p className="text-on-surface-variant">
          {t(
            "이 데이터셋은 아직 실험 디자인 분석이 진행되지 않았습니다.",
            "Experimental design has not been analyzed for this dataset yet.",
          )}
        </p>
        <button
          type="button"
          onClick={trigger}
          disabled={pending}
          className="mt-3 inline-flex h-8 items-center justify-center rounded-md bg-secondary px-3 text-body-sm font-medium text-on-secondary transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {pending
            ? t("분석 중… (5-15초)", "Analyzing… (5-15s)")
            : t("지금 분석하기", "Analyze now")}
        </button>
        {error ? <p className="mt-2 text-body-sm text-error">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-label-caps uppercase text-on-surface-variant">
          {t("실험 디자인", "Experimental design")}
        </h3>
        <span className="text-body-sm text-on-surface-variant">
          {designTypeLabel(result.design_type, locale)}
        </span>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {result.groups.map((g, i) => (
          <article
            key={`${g.label}-${i}`}
            className={`rounded-md border p-3 ${ROLE_STYLES[g.role]}`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <h4 className="truncate text-body-md font-medium">{g.label}</h4>
              {g.n != null ? (
                <span className="font-mono text-mono-data text-body-sm">N={g.n}</span>
              ) : null}
            </div>
            <div className="mt-0.5 text-label-caps uppercase opacity-70">
              {roleLabel(g.role, locale)}
            </div>
            {g.criteria ? (
              <p className="mt-2 line-clamp-3 text-body-sm leading-relaxed">{g.criteria}</p>
            ) : null}
          </article>
        ))}
      </div>

      {result.notes ? (
        <p className="rounded-md border border-outline-variant bg-surface-container-low/40 px-3 py-2 text-body-sm text-on-surface-variant">
          <span className="text-label-caps uppercase">{t("메모", "Notes")}</span>{" "}
          {result.notes}
        </p>
      ) : null}
    </div>
  );
}
