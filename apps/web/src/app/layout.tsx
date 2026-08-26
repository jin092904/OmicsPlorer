import type { Metadata } from "next";

import { NavigationPendingProvider } from "@/components/NavigationPending";
import { ThemeScript } from "@/components/ThemeScript";
import { getLocale } from "@/lib/i18n-server";
import { getTheme } from "@/lib/theme-server";

import "./globals.css";

export const metadata: Metadata = {
  title: "OmicsPlorer",
  description:
    "공공 생명정보 DB에서 연구 디자인에 가장 적합한 데이터셋을 시맨틱 매칭과 접근성 우선으로 찾아주는 검색 도구.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // SSR 단계에서 cookie 만으로 결정 가능한 값. system 은 클라이언트 JS (ThemeScript) 가 보정.
  const [locale, theme] = await Promise.all([getLocale(), getTheme()]);
  const ssrDark = theme === "dark";

  return (
    <html lang={locale} className={ssrDark ? "dark" : undefined} suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body className="bg-background text-on-background min-h-screen antialiased">
        <NavigationPendingProvider>{children}</NavigationPendingProvider>
      </body>
    </html>
  );
}
