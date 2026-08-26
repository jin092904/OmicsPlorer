import type { Locale, T } from "@/lib/i18n";
import { getSidebarState } from "@/lib/sidebar-server";

import { Footer } from "./Footer";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

// 모든 페이지의 셸 — desktop 좌측 sidebar (접기 가능) + 모바일 drawer 햄버거 (Header 내부) + 슬림 header + main + footer + 라우트 진행 바.
export async function AppShell({
  locale,
  t,
  initialQuery,
  showSearch = true,
  children,
}: {
  locale: Locale;
  t: T;
  initialQuery?: string;
  showSearch?: boolean;
  children: React.ReactNode;
}) {
  const sidebarState = await getSidebarState();
  return (
    <div className="flex min-h-screen w-full bg-background text-on-background">
      <Sidebar locale={locale} t={t} initialState={sidebarState} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header locale={locale} t={t} initialQuery={initialQuery} showSearch={showSearch} />
        <div className="flex flex-1 flex-col">{children}</div>
        <Footer t={t} />
      </div>
    </div>
  );
}
