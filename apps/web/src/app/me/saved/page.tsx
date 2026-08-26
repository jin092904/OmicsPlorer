import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { MemoryList } from "@/components/MemoryList";
import { getT } from "@/lib/i18n-server";

export default async function SavedPage() {
  const { locale, t } = await getT();
  // 찜은 비로그인도 localStorage 로 보이고, 로그인 시 서버 동기 → AuthGuard 제거.
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
          {locale === "ko" ? "찜한 데이터셋" : "Saved datasets"}
        </h1>
        <p className="mt-2 text-body-sm text-on-surface-variant">
          {locale === "ko"
            ? "찜한 데이터셋 목록입니다. 비로그인 시 이 브라우저에만 저장되며, 로그인하면 모든 기기에서 동기화됩니다."
            : "Your saved datasets. Stored in this browser when signed out; sign in to sync across devices."}
        </p>
        <div className="mt-7">
          <MemoryList kind="saved" locale={locale} />
        </div>
      </main>
    </AppShell>
  );
}
