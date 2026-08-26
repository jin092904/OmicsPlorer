// 작은 시각 prim — 모두 Tailwind class + globals.css 의 .gf-skeleton (shimmer) 결합.
//
// 가능하면 Skeleton 한 종류 (정사각/긴 직사각) 만 두고, 페이지별 형태는 helper 로 조합.

export function SkeletonLine({
  width = "100%",
  height = "0.85rem",
  className = "",
}: {
  width?: string;
  height?: string;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={`gf-skeleton block rounded-md ${className}`}
      style={{ width, height }}
    />
  );
}

export function SkeletonBlock({
  className = "",
  height = "10rem",
}: {
  className?: string;
  height?: string;
}) {
  return (
    <div
      aria-hidden
      className={`gf-skeleton w-full rounded-xl ${className}`}
      style={{ height }}
    />
  );
}

export function SkeletonCard() {
  return (
    <article className="flex flex-col gap-4 rounded-xl border border-outline-variant bg-surface p-6">
      <div className="flex items-center gap-2">
        <SkeletonLine width="2.5rem" height="1.1rem" />
        <SkeletonLine width="6rem" height="0.8rem" />
        <SkeletonLine width="5rem" height="0.8rem" className="ml-auto" />
      </div>
      <SkeletonLine width="80%" height="1.4rem" />
      <SkeletonLine width="60%" height="1rem" />
      <div className="flex flex-wrap gap-2">
        <SkeletonLine width="3.5rem" height="1.1rem" />
        <SkeletonLine width="4rem" height="1.1rem" />
        <SkeletonLine width="5rem" height="1.1rem" />
      </div>
      <div className="border-t border-outline-variant pt-4">
        <SkeletonLine width="100%" height="0.6rem" />
        <SkeletonLine width="80%" height="0.6rem" className="mt-2" />
      </div>
    </article>
  );
}

export function SkeletonHeader({ kicker = false }: { kicker?: boolean }) {
  return (
    <div className="space-y-3">
      {kicker ? <SkeletonLine width="6rem" height="0.7rem" /> : null}
      <SkeletonLine width="20rem" height="1.6rem" />
      <SkeletonLine width="14rem" height="0.95rem" />
    </div>
  );
}
