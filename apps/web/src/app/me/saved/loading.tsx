import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonLine } from "@/components/Skeleton";

export default function SavedLoading() {
  return (
    <LoadingShell>
      <div className="space-y-5">
        <SkeletonLine width="6rem" height="0.85rem" />
        <SkeletonLine width="14rem" height="1.6rem" />
        <SkeletonLine width="22rem" height="0.95rem" />
        <SkeletonBlock height="6rem" />
        <SkeletonBlock height="6rem" />
        <SkeletonBlock height="6rem" />
      </div>
    </LoadingShell>
  );
}
