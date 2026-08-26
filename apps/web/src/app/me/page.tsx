import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { MyHub } from "@/components/MyHub";
import { getT } from "@/lib/i18n-server";

export default async function MyPage() {
  const { locale, t } = await getT();
  return (
    <AppShell locale={locale} t={t} showSearch={false}>
      <main className="w-full flex-1 px-6 py-7 md:px-8">
        <AuthGuard locale={locale}>
          <MyHub locale={locale} />
        </AuthGuard>
      </main>
    </AppShell>
  );
}
