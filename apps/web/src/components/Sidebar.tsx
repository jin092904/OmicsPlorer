"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useRecentlyViewed, useSavedDatasets } from "@/lib/datasetMemory";
import type { Locale, T } from "@/lib/i18n";
import type { SidebarState } from "@/lib/sidebar";
import { useSidebar } from "@/lib/useSidebar";

import { SidebarUserBlock } from "./SidebarUserBlock";

type NavItem = {
  href: Route;
  label: string;
  icon: React.ReactNode;
  match: (path: string) => boolean;
};

export function Sidebar({
  locale,
  t,
  initialState,
  // 모바일 drawer 모드 — 항상 expanded 처럼 그리고 close 버튼 노출
  mobileDrawerMode = false,
  onCloseMobile,
}: {
  locale: Locale;
  t: T;
  initialState: SidebarState;
  mobileDrawerMode?: boolean;
  onCloseMobile?: () => void;
}) {
  const pathname = usePathname() ?? "/";
  const { collapsed: collapsedState, toggle } = useSidebar(initialState);
  const collapsed = mobileDrawerMode ? false : collapsedState;
  const { items: savedItems } = useSavedDatasets();
  const { items: recentItems } = useRecentlyViewed();

  const labels =
    locale === "ko"
      ? {
          version: "베타",
          newSearch: "새 검색",
          dashboard: "대시보드",
          browse: t.nav.datasets,
          librarySection: "내 라이브러리",
          saved: "찜한 데이터셋",
          recent: "최근 본",
          comingSoon: t.footer.comingSoon,
          feedback: "피드백",
          help: "도움말",
          collapse: "사이드바 접기",
          expand: "사이드바 펴기",
          close: "닫기",
        }
      : {
          version: "beta",
          newSearch: "New search",
          dashboard: "Dashboard",
          browse: t.nav.datasets,
          librarySection: "My library",
          saved: "Saved",
          recent: "Recently viewed",
          comingSoon: t.footer.comingSoon,
          feedback: "Feedback",
          help: "Help",
          collapse: "Collapse sidebar",
          expand: "Expand sidebar",
          close: "Close",
        };

  const items: NavItem[] = [
    {
      href: "/",
      label: labels.dashboard,
      match: (p) => p === "/",
      icon: <DashboardIcon />,
    },
    {
      href: "/search",
      label: labels.browse,
      match: (p) => p.startsWith("/search") || p.startsWith("/datasets"),
      icon: <BrowseIcon />,
    },
  ];

  const libraryItems: (NavItem & { count?: number })[] = [
    {
      href: "/me/saved",
      label: labels.saved,
      match: (p) => p.startsWith("/me/saved"),
      icon: <HeartIcon />,
      count: savedItems.length || undefined,
    },
    {
      href: "/me/recent",
      label: labels.recent,
      match: (p) => p.startsWith("/me/recent"),
      icon: <ClockIcon />,
      count: recentItems.length || undefined,
    },
  ];

  // 찜·최근은 비로그인도 localStorage 로 동작하므로 항상 노출(로그인 시 서버 동기).
  const showLibrary = true;

  const widthClass = collapsed ? "w-[64px]" : "w-64";
  const visibilityClass = mobileDrawerMode
    ? "flex h-screen w-72"
    : `sticky top-0 hidden h-screen ${widthClass} shrink-0 md:flex`;

  return (
    <aside
      className={`${visibilityClass} flex-col border-r border-outline-variant bg-surface transition-[width] duration-200 ease-out`}
      aria-label={locale === "ko" ? "주요 메뉴" : "Primary navigation"}
    >
      {/* Brand block — Header 와 동일한 padding + 자동 높이로 border 위치 정렬.
          (h-[60px] 명시하면 border-box 라 border 가 박스 안으로 들어가서 1px 어긋남.) */}
      <div
        className={`flex shrink-0 items-center border-b border-outline-variant py-3 ${
          collapsed ? "justify-center px-0" : "gap-3 px-5"
        }`}
      >
        <Link
          href="/"
          aria-label="OmicsPlorer"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-secondary text-on-secondary transition-opacity hover:opacity-90"
          onClick={mobileDrawerMode ? onCloseMobile : undefined}
        >
          <BrandMark />
        </Link>
        {!collapsed ? (
          <>
            <div className="min-w-0 flex-1">
              <Link
                href="/"
                className="block truncate text-headline-sm leading-tight text-on-surface transition-colors hover:text-secondary"
                onClick={mobileDrawerMode ? onCloseMobile : undefined}
              >
                OmicsPlorer
              </Link>
              <span className="text-label-caps uppercase text-on-surface-variant">
                v0.1 · {labels.version}
              </span>
            </div>
            {!mobileDrawerMode ? (
              <button
                type="button"
                onClick={toggle}
                aria-label={labels.collapse}
                title={labels.collapse}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
              >
                <ChevronIcon direction="left" />
              </button>
            ) : (
              <button
                type="button"
                onClick={onCloseMobile}
                aria-label={labels.close}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
              >
                <CloseIcon />
              </button>
            )}
          </>
        ) : null}
      </div>

      {/* Collapsed 모드 전용: brand 아래 별도 row 에 toggle (수직 정렬 보장) */}
      {collapsed && !mobileDrawerMode ? (
        <div className="flex h-9 shrink-0 items-center justify-center">
          <button
            type="button"
            onClick={toggle}
            aria-label={labels.expand}
            title={labels.expand}
            className="flex h-8 w-8 items-center justify-center rounded-md text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          >
            <ChevronIcon direction="right" />
          </button>
        </div>
      ) : null}

      {/* Primary CTA */}
      <div className={`mt-3 ${collapsed ? "flex justify-center px-0" : "px-4"}`}>
        <Link
          href="/search"
          onClick={mobileDrawerMode ? onCloseMobile : undefined}
          className={`flex items-center justify-center gap-2 rounded-md bg-primary text-on-primary transition-opacity hover:opacity-90 ${
            collapsed ? "h-10 w-10" : "w-full px-4 py-2.5 text-body-sm font-medium"
          }`}
          title={collapsed ? labels.newSearch : undefined}
          aria-label={collapsed ? labels.newSearch : undefined}
        >
          <PlusIcon />
          {!collapsed ? <span>{labels.newSearch}</span> : null}
        </Link>
      </div>

      {/* Nav */}
      <nav className={`mt-4 flex flex-col gap-0.5 ${collapsed ? "px-0" : "px-2.5"}`}>
        {items.map((it) => (
          <NavLink
            key={it.label}
            href={it.href}
            label={it.label}
            icon={it.icon}
            active={it.match(pathname)}
            collapsed={collapsed}
            onClick={mobileDrawerMode ? onCloseMobile : undefined}
          />
        ))}

        {/* 내 라이브러리 — 로그인 무관 노출(비로그인은 localStorage, 로그인은 서버 동기) */}
        {showLibrary ? (
          <>
            {collapsed ? (
              <div aria-hidden className="my-2 mx-3 border-t border-outline-variant" />
            ) : (
              <p className="mt-5 mb-1.5 px-3 text-label-caps uppercase text-on-surface-variant/80">
                {labels.librarySection}
              </p>
            )}
            {libraryItems.map((it) => (
              <NavLink
                key={it.label}
                href={it.href}
                label={it.label}
                icon={it.icon}
                active={it.match(pathname)}
                collapsed={collapsed}
                count={it.count}
                onClick={mobileDrawerMode ? onCloseMobile : undefined}
              />
            ))}
          </>
        ) : null}
      </nav>

      <div className="flex-1" />

      {/* Bottom: user + utilities */}
      <div className={`border-t border-outline-variant py-3 ${collapsed ? "px-2" : "px-3"}`}>
        <SidebarUserBlock locale={locale} collapsed={collapsed} onNavigate={onCloseMobile} />
        {!collapsed ? (
          <div className="mt-3 flex flex-col gap-0.5">
            <DisabledItem icon={<FeedbackIcon />} label={labels.feedback} title={labels.comingSoon} />
            <DisabledItem icon={<HelpIcon />} label={labels.help} title={labels.comingSoon} />
          </div>
        ) : null}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// pieces
// ---------------------------------------------------------------------------

function NavLink({
  href,
  label,
  icon,
  active,
  collapsed,
  count,
  onClick,
}: {
  href: Route;
  label: string;
  icon: React.ReactNode;
  active: boolean;
  collapsed: boolean;
  count?: number;
  onClick?: () => void;
}) {
  const base = active
    ? "bg-secondary-container/60 text-on-secondary-container"
    : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface";

  if (collapsed) {
    // 64px 폭 sidebar 안에서 40x40 정사각, 가로 정중앙 정렬.
    // count 가 있으면 우상단에 작은 dot 으로만 표시 (숫자 표시는 너무 좁음).
    const titleWithCount = typeof count === "number" ? `${label} (${count})` : label;
    return (
      <Link
        href={href}
        onClick={onClick}
        title={titleWithCount}
        aria-label={titleWithCount}
        className={`relative mx-auto flex h-10 w-10 items-center justify-center rounded-md transition-colors ${base}`}
      >
        <span aria-hidden>{icon}</span>
        {typeof count === "number" && count > 0 ? (
          <span
            aria-hidden
            className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-secondary"
          />
        ) : null}
      </Link>
    );
  }

  return (
    <Link
      href={href}
      onClick={onClick}
      className={`flex items-center gap-3 rounded-md px-3 py-2 text-body-sm font-medium transition-colors ${base}`}
    >
      <span aria-hidden>{icon}</span>
      <span className="flex-1">{label}</span>
      {typeof count === "number" ? (
        <span className="font-mono text-mono-data text-on-surface-variant/70">{count}</span>
      ) : null}
    </Link>
  );
}

function DisabledItem({
  icon,
  label,
  title,
}: {
  icon: React.ReactNode;
  label: string;
  title: string;
}) {
  return (
    <span
      title={title}
      className="flex cursor-not-allowed items-center gap-3 rounded-md px-3 py-1.5 text-body-sm text-on-surface-variant/50"
    >
      <span aria-hidden>{icon}</span>
      {label}
    </span>
  );
}

// ---------- icons ----------------------------------------------------------

function BrandMark() {
  // OmicsPlorer — 돋보기 렌즈(탐색) 안에 데이터 점(omics). Concept A.
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="10" cy="10" r="6.6" stroke="currentColor" strokeWidth="2.2" />
      <path d="M14.8 14.8 20 20" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <g fill="currentColor" stroke="none">
        <circle cx="8" cy="9" r="1.2" />
        <circle cx="12" cy="8.2" r="1.2" />
        <circle cx="10" cy="12" r="1.2" />
      </g>
    </svg>
  );
}
function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}
function DashboardIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </svg>
  );
}
function BrowseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}
function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {direction === "left" ? <path d="M15 6l-6 6 6 6" /> : <path d="M9 6l6 6-6 6" />}
    </svg>
  );
}
function CloseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}
function FeedbackIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}
function HeartIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z" />
    </svg>
  );
}
function ClockIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </svg>
  );
}
function HelpIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <path d="M12 17h.01" />
    </svg>
  );
}
