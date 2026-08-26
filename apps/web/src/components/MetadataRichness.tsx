// 데이터셋 메타데이터의 풍부도 시각화.
//
// 우리 코퍼스의 ~93% 가 v0-stub (placeholder) 추출 상태라 modality / organism / library_strategy
// 등 핵심 필드가 비어있는 경우가 많음. 이 컴포넌트는:
//   1. 어떤 필드가 채워졌는지 한눈에 (반원 도넛)
//   2. 채워진 필드 vs 빈 필드 체크리스트
//   3. v0-stub 상태일 때 안내 배너
// 를 한 번에 보여줘서 사용자가 "이 데이터셋 정보가 얼마나 충실한가" 를 빠르게 판단하게 한다.
import type { DatasetDetail } from "@/lib/api";
import type { Locale } from "@/lib/i18n";

type Field = { key: string; label: string; filled: boolean };

function buildFields(d: DatasetDetail, locale: Locale): Field[] {
  const isFilled = (v: unknown[]): boolean => Array.isArray(v) && v.length > 0;
  const isStr = (v: string | null | undefined): boolean => !!v && v.trim().length > 0;
  return [
    {
      key: "title",
      label: locale === "ko" ? "제목" : "Title",
      filled: isStr(d.title),
    },
    {
      key: "abstract",
      label: locale === "ko" ? "초록" : "Abstract",
      filled: isStr(d.abstract),
    },
    {
      key: "modality",
      label: locale === "ko" ? "모달리티" : "Modality",
      filled: isFilled(d.modality),
    },
    {
      key: "organism",
      label: locale === "ko" ? "종" : "Organism",
      filled: isFilled(d.organism_taxid),
    },
    {
      key: "library",
      label: locale === "ko" ? "라이브러리 전략" : "Library strategy",
      filled: isStr(d.library_strategy),
    },
    {
      key: "platform",
      label: locale === "ko" ? "플랫폼" : "Platform",
      filled: isStr(d.platform),
    },
    {
      key: "disease",
      label: locale === "ko" ? "질병" : "Disease",
      filled: isFilled(d.disease_ids ?? []),
    },
    {
      key: "tissue",
      label: locale === "ko" ? "조직" : "Tissue",
      filled: isFilled(d.tissue_ids ?? []),
    },
    {
      key: "cellType",
      label: locale === "ko" ? "세포 타입" : "Cell type",
      filled: isFilled(d.cell_type_ids ?? []),
    },
  ];
}

export function MetadataRichness({
  dataset,
  locale,
}: {
  dataset: DatasetDetail;
  locale: Locale;
}) {
  const fields = buildFields(dataset, locale);
  const filled = fields.filter((f) => f.filled).length;
  const total = fields.length;
  const pct = Math.round((filled / total) * 100);
  const isStub = (dataset.extraction_version ?? "").startsWith("v0-stub");

  const heading = locale === "ko" ? "정보 풍부도" : "Metadata richness";
  const subHeading =
    locale === "ko"
      ? `${filled} / ${total} 필드 채워짐`
      : `${filled} / ${total} fields populated`;
  const stubNote =
    locale === "ko"
      ? "이 데이터셋은 아직 풍부한 메타데이터 추출이 진행되지 않았습니다. 추출 작업이 완료되면 모달리티·종·질병 등이 자동으로 채워집니다."
      : "Rich metadata extraction has not been run on this dataset yet. Modality, organism, disease, and other fields will populate automatically once extraction completes.";

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-label-caps uppercase text-on-surface-variant">{heading}</h2>
        <span className="text-body-sm text-on-surface-variant">{subHeading}</span>
      </div>

      <div className="mt-3 flex items-center gap-5">
        {/* 도넛: 채워짐 비율 */}
        <Donut pct={pct} />
        {/* 체크리스트: 필드별 상태 */}
        <ul className="grid flex-1 grid-cols-1 gap-1 text-body-sm sm:grid-cols-2 md:grid-cols-3">
          {fields.map((f) => (
            <li
              key={f.key}
              className={`flex items-center gap-2 ${
                f.filled ? "text-on-surface" : "text-on-surface-variant/55"
              }`}
            >
              <span aria-hidden>{f.filled ? <CheckIcon /> : <DashIcon />}</span>
              <span className="truncate">{f.label}</span>
            </li>
          ))}
        </ul>
      </div>

      {isStub ? (
        <p className="mt-4 rounded-md border border-outline-variant bg-surface-container-low/60 px-3 py-2 text-body-sm text-on-surface-variant">
          {stubNote}
        </p>
      ) : null}
    </section>
  );
}

// 반원 progress (0-100%). SVG 로 그려서 다크모드도 자연스럽게 동작.
function Donut({ pct }: { pct: number }) {
  const size = 64;
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circ = 2 * Math.PI * radius;
  const offset = circ * (1 - pct / 100);

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgb(var(--surface-container-high))"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgb(var(--secondary))"
          strokeWidth={stroke}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <span
        className="absolute inset-0 flex items-center justify-center font-mono text-mono-data text-on-surface"
        style={{ fontSize: 13, fontWeight: 600 }}
      >
        {pct}%
      </span>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12l5 5L20 7" />
    </svg>
  );
}
function DashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
      <path d="M5 12h14" />
    </svg>
  );
}
