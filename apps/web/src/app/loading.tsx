import { LoadingShell } from "@/components/LoadingShell";
import { SkeletonBlock, SkeletonHeader } from "@/components/Skeleton";

export default function RootLoading() {
  return (
    <LoadingShell>
      <div className="flex flex-col gap-7">
        <SkeletonHeader kicker />
        <div className="grid gap-4 md:grid-cols-3">
          <SkeletonBlock height="9rem" />
          <SkeletonBlock height="9rem" />
          <SkeletonBlock height="9rem" />
        </div>
      </div>
    </LoadingShell>
  );
}
