// 코호트 분포 시각화 — 성비 도넛 + 연령 히스토그램 + condition / treatment 라벨 막대.
//
// 입력: CohortView.samples (api.ts). n_total === 0 인 경우 안내 메시지만 표시.
import type { CohortView } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

export function CohortBreakdown({
  samples,
  sourceSampleCount,
  locale,
}: {
  samples: CohortView["samples"];
  sourceSampleCount: number | null;
  locale: Locale;
}) {
  if (!samples || samples.n_total === 0) {
    return (
      <div className="rounded-md border border-outline-variant bg-surface-container-low/60 px-3 py-2 text-body-sm text-on-surface-variant">
        {locale === "ko"
          ? sourceSampleCount
            ? `파싱된 sample-level 메타데이터는 아직 없습니다. 원본은 샘플 ${sourceSampleCount}건을 보고합니다.`
            : "샘플 단위 메타데이터가 아직 수집되지 않은 데이터셋입니다."
          : sourceSampleCount
            ? `No parsed sample-level metadata yet. The source reports ${sourceSampleCount} samples.`
            : "No sample-level metadata yet for this dataset."}
      </div>
    );
  }

  const t = (ko: string, en: string) => (locale === "ko" ? ko : en);
  const { sex, age, disease_state, treatment, n_total } = samples;
  const sexTotal = (sex.male + sex.female + sex.unknown) || 1;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-label-caps uppercase text-on-surface-variant">
          {t("코호트 분포", "Cohort breakdown")}
        </h3>
        <span className="text-body-sm text-on-surface-variant">
          {t(`파싱된 메타데이터 ${n_total}건`, `${n_total} parsed metadata rows`)}
        </span>
      </header>

      {sourceSampleCount != null && sourceSampleCount !== n_total ? (
        <p className="-mt-2 text-body-sm text-on-surface-variant">
          {t(
            `원본 보고 샘플 수는 ${sourceSampleCount}건입니다.`,
            `The source reports ${sourceSampleCount} samples.`,
          )}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {/* 성비 도넛 */}
        <div>
          <div className="text-label-caps uppercase text-on-surface-variant">
            {t("성별", "Sex")}
          </div>
          <div className="mt-3 flex items-center gap-4">
            <SexDonut male={sex.male} female={sex.female} unknown={sex.unknown} />
            <ul className="flex flex-col gap-1 text-body-sm">
              <Legend color="bg-primary" label={t("남성", "Male")} n={sex.male} total={sexTotal} />
              <Legend
                color="bg-secondary"
                label={t("여성", "Female")}
                n={sex.female}
                total={sexTotal}
              />
              <Legend
                color="bg-outline-variant"
                label={t("미상", "Unknown")}
                n={sex.unknown}
                total={sexTotal}
              />
            </ul>
          </div>
        </div>

        {/* 연령 히스토그램 */}
        <div>
          <div className="text-label-caps uppercase text-on-surface-variant">
            {t("연령", "Age")}
          </div>
          {age.unit && age.buckets.length > 0 ? (
            <div className="mt-3">
              <div className="text-body-sm text-on-surface-variant">
                {t(
                  `${age.min}–${age.max} ${unitLabel(age.unit, locale)} · 중앙값 ${age.median}`,
                  `${age.min}–${age.max} ${unitLabel(age.unit, locale)} · median ${age.median}`,
                )}
              </div>
              <AgeBars buckets={age.buckets} />
            </div>
          ) : (
            <div className="mt-3 text-body-sm text-on-surface-variant/70">
              {t("연령 정보 없음", "Age data not available")}
            </div>
          )}
        </div>
      </div>

      {/* condition / treatment 라벨 */}
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        <LabelBars
          title={t("진단 / 그룹 라벨", "Condition / group label")}
          rows={disease_state}
          locale={locale}
        />
        <LabelBars
          title={t("처치 / 약물", "Treatment / drug")}
          rows={treatment}
          locale={locale}
        />
      </div>
    </div>
  );
}

function unitLabel(unit: string, locale: Locale): string {
  if (locale === "ko") {
    return unit === "year" ? "세" : unit === "month" ? "개월" : "일";
  }
  return unit;
}

function Legend({
  color,
  label,
  n,
  total,
}: {
  color: string;
  label: string;
  n: number;
  total: number;
}) {
  const pct = total > 0 ? Math.round((n / total) * 100) : 0;
  return (
    <li className="flex items-center gap-2">
      <span className={`inline-block h-2.5 w-2.5 rounded-sm ${color}`} aria-hidden />
      <span className="text-on-surface">{label}</span>
      <span className="font-mono text-mono-data text-on-surface-variant">
        {n} · {pct}%
      </span>
    </li>
  );
}

function SexDonut({
  male,
  female,
  unknown,
}: {
  male: number;
  female: number;
  unknown: number;
}) {
  const total = male + female + unknown || 1;
  const size = 96;
  const stroke = 14;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const seg = (n: number) => (n / total) * c;
  const maleDash = seg(male);
  const femaleDash = seg(female);
  const arcs = [
    { color: "rgb(var(--primary))", dash: maleDash, offset: 0 },
    { color: "rgb(var(--secondary))", dash: femaleDash, offset: maleDash },
    { color: "rgb(var(--outline-variant))", dash: seg(unknown), offset: maleDash + femaleDash },
  ];
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke="rgb(var(--surface-container-high))"
        strokeWidth={stroke}
      />
      {arcs.map(({ color, dash, offset }) => (
        <circle
          key={color}
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={`${dash} ${c - dash}`}
          strokeDashoffset={-offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      ))}
    </svg>
  );
}

function AgeBars({
  buckets,
}: {
  buckets: { lo: number; hi: number; count: number }[];
}) {
  const max = Math.max(...buckets.map((b) => b.count), 1);
  return (
    <div className="mt-2">
      {/* 막대 영역: ul 이 h-24, 각 li 가 h-full → 자식 div 의 height% 가 일관되게 계산됨 */}
      <ul className="flex h-24 items-end gap-2">
        {buckets.map((b, i) => (
          <li key={i} className="flex h-full flex-1 flex-col justify-end">
            <div
              className="w-full rounded-t-sm bg-secondary/70"
              style={{
                height: `${(b.count / max) * 100}%`,
                minHeight: b.count > 0 ? 4 : 0,
              }}
              title={`${Math.round(b.lo)}–${Math.round(b.hi)}: ${b.count}`}
            />
          </li>
        ))}
      </ul>
      {/* 라벨 영역: 별도 row. truncate 로 wrap 방지. */}
      <ul className="mt-1.5 flex gap-2">
        {buckets.map((b, i) => (
          <li
            key={i}
            className="flex-1 truncate text-center font-mono text-mono-data text-on-surface-variant/80"
            style={{ fontSize: 10 }}
            title={`${Math.round(b.lo)}–${Math.round(b.hi)}`}
          >
            {Math.round(b.lo)}–{Math.round(b.hi)}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LabelBars({
  title,
  rows,
  locale,
}: {
  title: string;
  rows: { label: string; count: number }[];
  locale: Locale;
}) {
  if (!rows || rows.length === 0) {
    return (
      <div>
        <div className="text-label-caps uppercase text-on-surface-variant">{title}</div>
        <div className="mt-2 text-body-sm text-on-surface-variant/55">
          {locale === "ko"
            ? "이 데이터셋의 sample characteristics 에 해당 항목 없음"
            : "Not recorded in this dataset's sample characteristics"}
        </div>
      </div>
    );
  }
  const max = Math.max(...rows.map((r) => r.count), 1);
  return (
    <div>
      <div className="text-label-caps uppercase text-on-surface-variant">{title}</div>
      <ul className="mt-2 flex flex-col gap-1.5">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2 text-body-sm">
            <span className="w-28 truncate text-on-surface" title={row.label}>
              {row.label}
            </span>
            <span className="relative h-2 flex-1 overflow-hidden rounded-sm bg-surface-container">
              <span
                className="absolute inset-y-0 left-0 bg-tertiary/70"
                style={{ width: `${(row.count / max) * 100}%` }}
              />
            </span>
            <span className="w-8 text-right font-mono text-mono-data text-on-surface-variant">
              {row.count}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
