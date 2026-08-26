import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { LoginPanel } from "@/components/LoginPanel";
import { getT } from "@/lib/i18n-server";

type SearchParams = { next?: string };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { locale, t } = await getT();
  const params = await searchParams;
  const next = sanitizeNext(params?.next);

  const copy =
    locale === "ko"
      ? {
          title: "OmicsPlorer 로그인",
          subtitle:
            "구글 계정으로 로그인하면 찜한 데이터셋과 최근 본 데이터셋을 기기 간에 동기화할 수 있고, 곧 공개될 커뮤니티에도 자동으로 연결됩니다.",
          terms: "로그인 시 이용약관과 개인정보 처리방침에 동의하게 됩니다.",
          backHome: "← 메인으로",
        }
      : {
          title: "Sign in to OmicsPlorer",
          subtitle:
            "Sign in with Google to sync saved and recently-viewed datasets across devices, and to connect to the upcoming community space.",
          terms: "By signing in you agree to our Terms and Privacy Policy.",
          backHome: "← Back to home",
        };

  return (
    <AppShell locale={locale} t={t} showSearch={false}>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-stretch px-6 py-12">
        <Link
          href="/"
          className="text-body-sm text-on-surface-variant transition-colors hover:text-on-surface"
        >
          {copy.backHome}
        </Link>
        <h1 className="mt-6 text-headline-lg text-on-surface">{copy.title}</h1>
        <p className="mt-3 text-body-md text-on-surface-variant">{copy.subtitle}</p>

        <div className="mt-8">
          <LoginPanel locale={locale} next={next} />
        </div>

        <p className="mt-8 text-body-sm text-on-surface-variant/70">{copy.terms}</p>
      </main>
    </AppShell>
  );
}

// open-redirect 방어: 절대 URL 거부, 같은-사이트 경로만 허용.
function sanitizeNext(raw: string | undefined): string {
  if (!raw) return "/me";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/me";
  return raw;
}
