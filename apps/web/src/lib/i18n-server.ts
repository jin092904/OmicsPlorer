// Server-only — `next/headers` 는 server component / route handler 에서만 import 가능.
import "server-only";

import { translations, type Locale, type T } from "./i18n";

// 한글 UI 비활성화 — 영어로 고정(2026-07-03 런칭 준비). 쿠키 무시.
// 검색 입력의 다국어 허용/자동번역은 별개(auto_translate 토글로 처리).
// 되돌리려면: cookies() 로 LOCALE_COOKIE 를 다시 읽어 en/ko 분기.
export async function getLocale(): Promise<Locale> {
  return "en";
}

// 검색 자동번역(비영어→영어) on/off. 쿠키 `auto_translate`, 기본 OFF('1'일 때만 ON).
// 영어 검색 권장 방침 + 현 서버 번역모델 콜드로드 지연 회피 위해 opt-in.
export async function getAutoTranslate(): Promise<boolean> {
  const { cookies } = await import("next/headers");
  return (await cookies()).get("auto_translate")?.value === "1";
}

export async function getT(): Promise<{ locale: Locale; t: T }> {
  const locale = await getLocale();
  // `translations` 는 `as const` 라 ko / en 의 literal 타입이 다름 — runtime 동등성은 보장되니 cast.
  return { locale, t: translations[locale] as unknown as T };
}
