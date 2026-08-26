import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { MemoryList } from "@/components/MemoryList";
import { getT } from "@/lib/i18n-server";

export default async function RecentPage() {
  const { locale, t } = await getT();
  // 최근 본 데이터셋은 localStorage 단독(비로그인 포함) → AuthGuard 제거.
  return (
    <AppShell locale={locale} t={t} showSearch={false}>
      <main className="w-full flex-1 px-6 py-7 md:px-8">
        <Link
          href="/me"
          className="text-body-sm text-on-surface-variant transition-colors hover:text-on-surface"
        >
          {locale === "ko" ? "← 마이페이지" : "← My page"}
        </Link>
        <h1 className="mt-3 text-headline-md text-on-surface">
          {locale === "ko" ? "최근 본 데이터셋" : "Recently viewed"}
        </h1>
        <p className="mt-2 text-body-sm text-on-surface-variant">
          {locale === "ko"
            ? "이 브라우저에 저장된 최근 20건입니다. (찜과 달리 다른 기기로는 동기화되지 않습니다.)"
            : "Last 20 datasets stored in this browser (not synced across devices)."}
        </p>
        <div className="mt-7">
          <MemoryList kind="recent" locale={locale} />
        </div>
      </main>
    </AppShell>
  );
}
