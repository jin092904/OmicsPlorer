import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonLine } from "@/components/Skeleton";

export default function LoginLoading() {
  return (
    <LoadingShell>
      <div className="mx-auto max-w-md space-y-5">
        <SkeletonLine width="6rem" height="0.85rem" />
        <SkeletonLine width="80%" height="2rem" />
        <SkeletonLine width="100%" height="0.95rem" />
        <SkeletonLine width="80%" height="0.95rem" />
        <SkeletonBlock height="3rem" />
      </div>
    </LoadingShell>
  );
}
