import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { AuthGuard } from "@/components/AuthGuard";
import { SettingsForm } from "@/components/SettingsForm";
import { getT } from "@/lib/i18n-server";

export default async function SettingsPage() {
  const { locale, t } = await getT();
  return (
    <AppShell locale={locale} t={t} showSearch={false}>
      <main className="mx-auto w-full max-w-2xl flex-1 px-6 py-7 md:px-8">
        <AuthGuard locale={locale}>
          <Link
            href="/me"
            className="text-body-sm text-on-surface-variant transition-colors hover:text-on-surface"
          >
            {locale === "ko" ? "← 마이페이지" : "← My page"}
          </Link>
          <h1 className="mt-3 text-headline-md text-on-surface">
            {locale === "ko" ? "프로필 / 설정" : "Profile & Settings"}
          </h1>
          <p className="mt-2 text-body-sm text-on-surface-variant">
            {locale === "ko"
              ? "닉네임, 언어, 테마를 변경할 수 있습니다. 닉네임은 곧 공개될 커뮤니티에서 다른 사용자에게 보이는 이름입니다."
              : "Change your nickname, language, and theme. Nickname will be shown in the upcoming community."}
          </p>
          <div className="mt-8">
            <SettingsForm locale={locale} />
          </div>
        </AuthGuard>
      </main>
    </AppShell>
  );
}
