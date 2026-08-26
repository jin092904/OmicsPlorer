import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonLine } from "@/components/Skeleton";

export default function DatasetLoading() {
  return (
    <LoadingShell>
      <div className="space-y-6">
        <SkeletonLine width="6rem" height="0.85rem" />
        <div className="space-y-3">
          <SkeletonLine width="80%" height="1.7rem" />
          <SkeletonLine width="60%" height="1rem" />
        </div>
        <SkeletonBlock height="12rem" />
        <SkeletonBlock height="8rem" />
        <SkeletonBlock height="6rem" />
      </div>
    </LoadingShell>
  );
}
