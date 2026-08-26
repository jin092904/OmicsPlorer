import "server-only";

import { cookies } from "next/headers";

import { isSidebarState, SIDEBAR_COOKIE, type SidebarState } from "./sidebar";

export async function getSidebarState(): Promise<SidebarState> {
  const c = (await cookies()).get(SIDEBAR_COOKIE);
  if (c && isSidebarState(c.value)) return c.value;
  return "expanded";
}
