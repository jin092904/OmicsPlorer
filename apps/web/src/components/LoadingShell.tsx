import { getT } from "@/lib/i18n-server";

import { AppShell } from "./AppShell";

// loading.tsx 들이 공유하는 셸 — 사이드바/헤더는 그대로 보여주고 본문만 skeleton.
export async function LoadingShell({ children }: { children: React.ReactNode }) {
  const { locale, t } = await getT();
  return (
    <AppShell locale={locale} t={t} showSearch={false}>
      <main className="w-full flex-1 px-6 py-7 md:px-8" aria-busy="true">
        {children}
      </main>
    </AppShell>
  );
}
