// Sidebar 접힘 상태. 서버/클라이언트 양쪽에서 import 가능 (쿠키 키 + 타입).
export type SidebarState = "expanded" | "collapsed";

export const SIDEBAR_COOKIE = "sidebar";

export function isSidebarState(v: string | undefined): v is SidebarState {
  return v === "expanded" || v === "collapsed";
}
