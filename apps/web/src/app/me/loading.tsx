import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonLine } from "@/components/Skeleton";

export default function MyLoading() {
  return (
    <LoadingShell>
      <div className="space-y-7">
        <SkeletonBlock height="6.5rem" />
        <div className="grid gap-4 sm:grid-cols-2">
          <SkeletonBlock height="9rem" />
          <SkeletonBlock height="9rem" />
          <SkeletonBlock height="9rem" />
          <SkeletonBlock height="9rem" />
        </div>
        <SkeletonLine width="40%" />
      </div>
    </LoadingShell>
  );
}
