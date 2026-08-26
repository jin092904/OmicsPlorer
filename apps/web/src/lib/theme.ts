// 테마 토큰 + 쿠키 키. 서버/클라이언트 양쪽에서 import 가능.
export type Theme = "light" | "dark" | "system";

export const THEME_COOKIE = "theme";

export function isTheme(v: string | undefined): v is Theme {
  return v === "light" || v === "dark" || v === "system";
}
