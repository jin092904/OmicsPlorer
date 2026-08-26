"use client";

import { useEffect, useRef, useState } from "react";

import { useSearchParams } from "next/navigation";

import { useNavigation } from "@/components/NavigationPending";
import type { Facets } from "@/lib/api";
import type { T } from "@/lib/i18n";

// 정식 모달리티 어휘(backend ALLOWED_MODALITIES 와 동일) — "표시 순서"로만 사용.
// 실제 표시 목록은 검색 결과 facet(에 존재하는 값)에서 동적으로 만든다(아래 buildModalityOptions).
// 과거엔 이 배열을 그대로 렌더해 snRNA-seq·long-read·scMultiome 등 facet 에 있는데도
// 목록에 없는 값이 필터에서 통째로 누락됐다.
const MODALITY_ORDER: string[] = [
  // 단일세포 / 공간 전사체
  "scRNA-seq", "snRNA-seq", "spatial", "scMultiome", "CITE-seq",
  // bulk 전사체
  "bulk RNA-seq", "smallRNA-seq", "Ribo-seq", "GRO-seq",
  // 염색질 / 후성유전
  "scATAC-seq", "ATAC-seq", "ChIP-seq", "CUT&RUN", "Hi-C", "methylation",
  // RNA-단백질
  "RIP-seq", "CLIP-seq",
  // 유전체
  "WGS", "WES",
  // 마이크로바이옴
  "16S", "amplicon", "metagenomics",
  // 기타 기술
  "long-read", "proteomics",
  // 어레이
  "microarray", "SNP-array", "ChIP-chip", "RT-PCR",
  // fallback
  "other",
];

// 표시할 모달리티 옵션 = (결과 facet 에 존재하는 값) ∪ (현재 선택된 값) 을 정식 순서로 정렬.
// - facet 에 있는 건 전부 노출(snRNA-seq 등 누락 방지) + 카운트 표시.
// - 선택된 값은 facet 에 없어도 유지(체크 해제 가능하도록).
// - facet 자체가 없으면(검색 전 등) 전체 정식 목록으로 폴백.
function buildModalityOptions(facets: Facets | undefined, selected: string[]): string[] {
  const present = (facets?.modality ?? []).map((f) => f.value);
  const base = present.length > 0 ? present : MODALITY_ORDER;
  const union = Array.from(new Set([...base, ...selected]));
  const countOf = (v: string) =>
    facets?.modality.find((f) => f.value === v)?.count ?? 0;
  const orderIdx = (v: string) => {
    const i = MODALITY_ORDER.indexOf(v);
    return i === -1 ? MODALITY_ORDER.length : i;
  };
  return union.sort((a, b) => orderIdx(a) - orderIdx(b) || countOf(b) - countOf(a));
}

const SOURCE_DB_OPTIONS = ["GEO", "SRA", "ENA", "HCA", "GDC"];

// 필터 선택 묶음(draft). URL(=적용된 상태)과 별개로, 사용자가 체크하다가 "적용"을 눌러야 검색에 반영.
type Draft = {
  modality: string[];
  source_db: string[];
  disease: string[];
  tissue: string[];
  cell_type: string[];
  access: "any" | "open_only";
  processed: boolean;
  conj: { modality: boolean; disease: boolean; tissue: boolean; cell_type: boolean };
};

// dirty 비교/동기화용 정규화 키 — 배열 순서 무시 + conj 는 값 2개 이상일 때만 유효.
function keyOf(d: Draft): string {
  return JSON.stringify({
    modality: [...d.modality].sort(),
    source_db: [...d.source_db].sort(),
    disease: [...d.disease].sort(),
    tissue: [...d.tissue].sort(),
    cell_type: [...d.cell_type].sort(),
    access: d.access,
    processed: d.processed,
    conj: {
      modality: d.conj.modality && d.modality.length >= 2,
      disease: d.conj.disease && d.disease.length >= 2,
      tissue: d.conj.tissue && d.tissue.length >= 2,
      cell_type: d.conj.cell_type && d.cell_type.length >= 2,
    },
  });
}

const EMPTY_DRAFT: Draft = {
  modality: [],
  source_db: [],
  disease: [],
  tissue: [],
  cell_type: [],
  access: "open_only",
  processed: false,
  conj: { modality: false, disease: false, tissue: false, cell_type: false },
};

export function Filters({
  selectedModality,
  selectedSourceDb,
  selectedDisease,
  selectedTissue,
  selectedCellType,
  accessPreference,
  mustHaveProcessedData,
  conjunctionModes,
  query,
  t,
  facets,
  locale,
  ontologyLabels,
}: {
  selectedModality: string[];
  selectedSourceDb: string[];
  selectedDisease: string[];
  selectedTissue: string[];
  selectedCellType: string[];
  accessPreference: "any" | "open_only";
  mustHaveProcessedData: boolean;
  conjunctionModes: {
    modality: "all" | null;
    disease: "all" | null;
    tissue: "all" | null;
    cell_type: "all" | null;
  };
  query: string;
  t: T;
  facets?: Facets;
  locale: "ko" | "en";
  ontologyLabels?: Record<string, string>;
}) {
  const modalityCounts = new Map(facets?.modality.map((f) => [f.value, f.count]) ?? []);
  const sourceCounts = new Map(facets?.source_db.map((f) => [f.value, f.count]) ?? []);
  const diseaseFacets = facets?.disease_ids ?? [];
  const tissueFacets = facets?.tissue_ids ?? [];
  const cellTypeFacets = facets?.cell_type_ids ?? [];
  const labelOf = (curie: string) => ontologyLabels?.[curie] ?? curie;
  const tt = (ko: string, en: string) => (locale === "ko" ? ko : en);

  const { navigate, isPending } = useNavigation();
  const searchParams = useSearchParams();

  // URL 에서 파생된 "적용된" 상태.
  const applied: Draft = {
    modality: selectedModality,
    source_db: selectedSourceDb,
    disease: selectedDisease,
    tissue: selectedTissue,
    cell_type: selectedCellType,
    access: accessPreference,
    processed: mustHaveProcessedData,
    conj: {
      modality: conjunctionModes.modality === "all",
      disease: conjunctionModes.disease === "all",
      tissue: conjunctionModes.tissue === "all",
      cell_type: conjunctionModes.cell_type === "all",
    },
  };
  const appliedKey = keyOf(applied);

  // draft: 사용자가 만지는 임시 상태. 네비게이션 후(applied 변경) 동기화하되,
  // 적용 대기 중(in-flight) 사용자가 추가로 만진 편집은 덮어쓰지 않는다.
  const [draft, setDraft] = useState<Draft>(applied);
  const prevAppliedKey = useRef(appliedKey);
  useEffect(() => {
    if (appliedKey === prevAppliedKey.current) return; // 필터 변동 없는 렌더 → 무시
    // 네비게이션이 커밋됨. draft 가 "직전 적용본"과 같으면(=사용자가 그새 안 만짐) 새 적용본으로
    // 재동기화. 다르면(=in-flight 중 사용자가 편집함) draft 유지해 편집 보존.
    setDraft((d) => (keyOf(d) === prevAppliedKey.current ? applied : d));
    prevAppliedKey.current = appliedKey;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appliedKey]);

  const dirty = keyOf(draft) !== appliedKey;

  // draft → /search URL. q·sort 는 보존, page 는 리셋(생략).
  const buildHref = (d: Draft): string => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    const sort = searchParams.get("sort");
    if (sort) params.set("sort", sort);
    for (const m of d.modality) params.append("modality", m);
    for (const s of d.source_db) params.append("source_db", s);
    for (const x of d.disease) params.append("disease", x);
    for (const x of d.tissue) params.append("tissue", x);
    for (const x of d.cell_type) params.append("cell_type", x);
    if (d.access === "any") params.set("access", "any");
    if (d.processed) params.set("processed", "1");
    if (d.conj.modality && d.modality.length >= 2) params.set("modality_conjunction", "all");
    if (d.conj.disease && d.disease.length >= 2) params.set("disease_conjunction", "all");
    if (d.conj.tissue && d.tissue.length >= 2) params.set("tissue_conjunction", "all");
    if (d.conj.cell_type && d.cell_type.length >= 2) params.set("cell_type_conjunction", "all");
    return `/search?${params.toString()}`;
  };

  const applyDraft = () => {
    if (!dirty) return;
    navigate(buildHref(draft) as Parameters<typeof navigate>[0]);
  };

  const toggleArr = (field: "modality" | "source_db" | "disease" | "tissue" | "cell_type", value: string) =>
    setDraft((d) => {
      const cur = d[field];
      return {
        ...d,
        [field]: cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value],
      };
    });

  const setConj = (field: "modality" | "disease" | "tissue" | "cell_type", v: boolean) =>
    setDraft((d) => ({ ...d, conj: { ...d.conj, [field]: v } }));

  // "모두 해제": draft 만 비움(적용은 버튼으로). 이미 적용된 게 있으면 dirty → 적용 버튼 활성.
  const clearAll = () => setDraft(EMPTY_DRAFT);

  const ontoLabels =
    locale === "ko"
      ? { disease: "질병", tissue: "조직", cellType: "세포 타입" }
      : { disease: "Disease", tissue: "Tissue", cellType: "Cell type" };

  return (
    <aside className="sticky top-24 flex max-h-[calc(100vh-7rem)] flex-col overflow-y-auto rounded-xl border border-outline-variant bg-surface">
      {/* 스크롤해도 항상 보이는 헤더 + 적용 버튼 */}
      <div className="sticky top-0 z-10 border-b border-outline-variant bg-surface px-6 pb-3 pt-5">
        <div className="flex items-center justify-between">
          <h2 className="text-headline-sm text-on-surface">{t.filters.heading}</h2>
          <button
            type="button"
            onClick={clearAll}
            className="text-body-sm font-medium text-secondary transition-opacity hover:opacity-70"
          >
            {t.filters.clearAll}
          </button>
        </div>
        <button
          type="button"
          onClick={applyDraft}
          disabled={!dirty || isPending}
          className={`mt-3 w-full rounded-full px-4 py-2 text-body-sm font-semibold transition-colors ${
            dirty
              ? "bg-secondary text-on-secondary hover:bg-secondary/90"
              : "cursor-default border border-outline-variant bg-surface text-on-surface-variant"
          }`}
        >
          {isPending
            ? tt("적용 중…", "Applying…")
            : dirty
              ? tt("이 필터로 검색", "Search with filters")
              : tt("필터 적용됨", "Filters applied")}
        </button>
      </div>

      <div className="flex flex-col gap-7 px-6 py-5">
        <FilterGroup
          label={t.filters.modality}
          andToggle={
            draft.modality.length >= 2 ? (
              <AndToggle
                checked={draft.conj.modality}
                label={t.filters.mustIncludeAll}
                title={t.filters.mustIncludeAllHint}
                onChange={(v) => setConj("modality", v)}
              />
            ) : null
          }
        >
          {buildModalityOptions(facets, draft.modality).map((opt) => (
            <Checkbox
              key={opt}
              checked={draft.modality.includes(opt)}
              label={opt}
              count={modalityCounts.get(opt)}
              onChange={() => toggleArr("modality", opt)}
            />
          ))}
        </FilterGroup>

        <FilterGroup label={t.filters.sourceDb}>
          {SOURCE_DB_OPTIONS.map((opt) => (
            <Checkbox
              key={opt}
              checked={draft.source_db.includes(opt)}
              label={opt}
              count={sourceCounts.get(opt)}
              onChange={() => toggleArr("source_db", opt)}
            />
          ))}
        </FilterGroup>

        <FilterGroup label={t.filters.access}>
          <Radio
            name="access"
            checked={draft.access === "any"}
            label={t.filters.accessAny}
            onChange={() => setDraft((d) => ({ ...d, access: "any" }))}
          />
          <Radio
            name="access"
            checked={draft.access === "open_only"}
            label={t.filters.accessOpen}
            onChange={() => setDraft((d) => ({ ...d, access: "open_only" }))}
          />
        </FilterGroup>

        <FilterGroup label={t.filters.dataAvailability}>
          <Checkbox
            checked={draft.processed}
            label={t.filters.hasProcessed}
            onChange={() => setDraft((d) => ({ ...d, processed: !d.processed }))}
          />
        </FilterGroup>

        {diseaseFacets.length > 0 ? (
          <FilterGroup
            label={ontoLabels.disease}
            andToggle={
              draft.disease.length >= 2 ? (
                <AndToggle
                  checked={draft.conj.disease}
                  label={t.filters.mustIncludeAll}
                  title={t.filters.mustIncludeAllHint}
                  onChange={(v) => setConj("disease", v)}
                />
              ) : null
            }
          >
            {diseaseFacets.slice(0, 8).map((f) => (
              <Checkbox
                key={f.value}
                checked={draft.disease.includes(f.value)}
                label={labelOf(f.value)}
                count={f.count}
                onChange={() => toggleArr("disease", f.value)}
              />
            ))}
          </FilterGroup>
        ) : null}

        {tissueFacets.length > 0 ? (
          <FilterGroup
            label={ontoLabels.tissue}
            andToggle={
              draft.tissue.length >= 2 ? (
                <AndToggle
                  checked={draft.conj.tissue}
                  label={t.filters.mustIncludeAll}
                  title={t.filters.mustIncludeAllHint}
                  onChange={(v) => setConj("tissue", v)}
                />
              ) : null
            }
          >
            {tissueFacets.slice(0, 8).map((f) => (
              <Checkbox
                key={f.value}
                checked={draft.tissue.includes(f.value)}
                label={labelOf(f.value)}
                count={f.count}
                onChange={() => toggleArr("tissue", f.value)}
              />
            ))}
          </FilterGroup>
        ) : null}

        {cellTypeFacets.length > 0 ? (
          <FilterGroup
            label={ontoLabels.cellType}
            andToggle={
              draft.cell_type.length >= 2 ? (
                <AndToggle
                  checked={draft.conj.cell_type}
                  label={t.filters.mustIncludeAll}
                  title={t.filters.mustIncludeAllHint}
                  onChange={(v) => setConj("cell_type", v)}
                />
              ) : null
            }
          >
            {cellTypeFacets.slice(0, 8).map((f) => (
              <Checkbox
                key={f.value}
                checked={draft.cell_type.includes(f.value)}
                label={labelOf(f.value)}
                count={f.count}
                onChange={() => toggleArr("cell_type", f.value)}
              />
            ))}
          </FilterGroup>
        ) : null}
      </div>
    </aside>
  );
}

function FilterGroup({
  label,
  andToggle,
  children,
}: {
  label: string;
  andToggle?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-label-caps uppercase text-on-surface-variant">{label}</h3>
        {andToggle}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function AndToggle({
  checked,
  label,
  title,
  onChange,
}: {
  checked: boolean;
  label: string;
  title?: string;
  onChange: (v: boolean) => void;
}) {
  return (
    <label
      title={title}
      className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-2 py-0.5 text-label-caps transition-colors ${
        checked
          ? "border-secondary bg-secondary-container/40 text-secondary"
          : "border-outline-variant text-on-surface-variant hover:text-secondary"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3 w-3 cursor-pointer rounded border-outline-variant text-secondary focus:ring-1 focus:ring-secondary/30"
      />
      <span>AND · {label}</span>
    </label>
  );
}

function Checkbox({
  checked,
  label,
  count,
  onChange,
}: {
  checked: boolean;
  label: string;
  count?: number;
  onChange: () => void;
}) {
  return (
    <label className="group flex cursor-pointer items-center justify-between gap-3 py-0.5">
      <span className="flex min-w-0 items-center gap-2.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={onChange}
          className="h-4 w-4 cursor-pointer rounded border-outline-variant text-secondary focus:ring-1 focus:ring-secondary/30"
        />
        <span className="truncate text-body-sm text-on-surface transition-colors group-hover:text-secondary">
          {label}
        </span>
      </span>
      {typeof count === "number" ? (
        <span className="shrink-0 font-mono text-mono-data text-on-surface-variant">{count}</span>
      ) : null}
    </label>
  );
}

function Radio({
  name,
  checked,
  label,
  onChange,
}: {
  name: string;
  checked: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <label className="group flex cursor-pointer items-center gap-2.5 py-0.5">
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onChange}
        className="h-4 w-4 cursor-pointer border-outline-variant text-secondary focus:ring-1 focus:ring-secondary/30"
      />
      <span className="text-body-sm text-on-surface transition-colors group-hover:text-secondary">
        {label}
      </span>
    </label>
  );
}
