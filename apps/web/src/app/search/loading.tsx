import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonCard, SkeletonLine } from "@/components/Skeleton";

export default function SearchLoading() {
  return (
    <LoadingShell>
      <div className="grid grid-cols-1 gap-7 md:grid-cols-12">
        {/* 필터 사이드 */}
        <aside className="space-y-4 md:col-span-3">
          <SkeletonLine width="5rem" height="1rem" />
          <SkeletonBlock height="14rem" />
          <SkeletonBlock height="10rem" />
        </aside>

        {/* 결과 영역 */}
        <section className="space-y-4 md:col-span-9">
          <SkeletonLine width="60%" height="1.6rem" />
          <SkeletonLine width="30%" height="0.9rem" />
          <div className="mt-3 flex flex-col gap-4">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        </section>
      </div>
    </LoadingShell>
  );
}
