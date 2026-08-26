import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonLine } from "@/components/Skeleton";

export default function SettingsLoading() {
  return (
    <LoadingShell>
      <div className="mx-auto max-w-2xl space-y-6">
        <SkeletonLine width="6rem" height="0.85rem" />
        <SkeletonLine width="50%" height="1.6rem" />
        <SkeletonLine width="80%" height="0.95rem" />
        <SkeletonBlock height="13rem" />
        <SkeletonBlock height="13rem" />
      </div>
    </LoadingShell>
  );
}
