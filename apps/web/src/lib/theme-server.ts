import "server-only";

import { cookies } from "next/headers";

import { isTheme, THEME_COOKIE, type Theme } from "./theme";

export async function getTheme(): Promise<Theme> {
  const c = (await cookies()).get(THEME_COOKIE);
  if (c && isTheme(c.value)) return c.value;
  return "system";
}
