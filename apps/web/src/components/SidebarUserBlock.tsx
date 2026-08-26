"use client";

import type { Route } from "next";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { displayNameOf, useProfile } from "@/lib/useProfile";
import { useUser } from "@/lib/user";

export function SidebarUserBlock({
  locale,
  collapsed = false,
  onNavigate,
}: {
  locale: "ko" | "en";
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const { user, loading } = useUser();
  const { profile } = useProfile();
  const pathname = usePathname() ?? "/";

  const labels =
    locale === "ko"
      ? { signIn: "로그인", mypage: "마이페이지" }
      : { signIn: "Sign in", mypage: "My page" };

  if (loading) {
    return <div className="h-11 animate-pulse rounded-md bg-surface-container/60" />;
  }

  if (!user) {
    const next = pathname && pathname !== "/login" ? `?next=${encodeURIComponent(pathname)}` : "";
    return (
      <Link
        href={`/login${next}` as Route}
        onClick={onNavigate}
        title={labels.signIn}
        aria-label={labels.signIn}
        className={`flex items-center justify-center gap-2 rounded-md border border-outline-variant text-body-sm font-medium text-on-surface-variant transition-colors hover:border-on-surface-variant/50 hover:text-on-surface ${
          collapsed ? "h-10 w-10 mx-auto" : "w-full px-3 py-2"
        }`}
      >
        {collapsed ? <SignInIcon /> : <span>{labels.signIn}</span>}
      </Link>
    );
  }

  const shown = displayNameOf(profile, user);
  const photo = profile?.picture ?? user.photoURL;
  const initial = (shown || "?").charAt(0).toUpperCase();
  const email = profile?.email ?? user.email;

  if (collapsed) {
    return (
      <Link
        href="/me"
        onClick={onNavigate}
        title={`${shown}${email ? ` · ${email}` : ""}`}
        aria-label={labels.mypage}
        className="mx-auto flex h-10 w-10 items-center justify-center rounded-md transition-colors hover:bg-surface-container"
      >
        {photo ? (
          <Image
            src={photo}
            alt=""
            width={32}
            height={32}
            className="rounded-full"
            referrerPolicy="no-referrer"
            unoptimized
          />
        ) : (
          <span className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-on-secondary text-body-sm font-semibold">
            {initial}
          </span>
        )}
      </Link>
    );
  }

  return (
    <Link
      href="/me"
      onClick={onNavigate}
      className="flex w-full items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-surface-container"
      title={labels.mypage}
    >
      {photo ? (
        <Image
          src={photo}
          alt=""
          width={32}
          height={32}
          className="rounded-full"
          referrerPolicy="no-referrer"
          unoptimized
        />
      ) : (
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-on-secondary text-body-sm font-semibold">
          {initial}
        </span>
      )}
      <div className="min-w-0 flex-1 text-left">
        <div className="truncate text-body-sm font-medium text-on-surface">{shown}</div>
        {email ? (
          <div className="truncate text-on-surface-variant/80" style={{ fontSize: 11 }}>
            {email}
          </div>
        ) : null}
      </div>
    </Link>
  );
}

function SignInIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
      <path d="m10 17 5-5-5-5M15 12H3" />
    </svg>
  );
}
