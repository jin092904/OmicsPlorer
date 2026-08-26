"use client";

import type { Route } from "next";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { displayNameOf, useProfile } from "@/lib/useProfile";
import { useUser } from "@/lib/user";

// 헤더 우측 아바타. Sidebar 가 이미 사용자 정체성을 표시하므로 본 메뉴는 액션만:
//   My page · Settings · Sign out
// 비로그인 상태에서는 아예 노출하지 않음 — 사이드바의 sign-in 으로 단일 진입점 통일.
export function UserMenu({ locale }: { locale: "ko" | "en" }) {
  const { user, loading, signOut } = useUser();
  const { profile } = useProfile();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // 라우트 변경 시 자동으로 닫기
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const labels =
    locale === "ko"
      ? {
          mypage: "마이페이지",
          settings: "설정",
          logout: "로그아웃",
        }
      : {
          mypage: "My page",
          settings: "Settings",
          logout: "Sign out",
        };

  if (loading) {
    return (
      <div className="h-9 w-9 animate-pulse rounded-full border border-outline-variant bg-surface-container/60" />
    );
  }

  // 비로그인 시 헤더에서 사라짐 — 사이드바의 sign-in 블록이 단일 CTA.
  if (!user) return null;

  const shown = displayNameOf(profile, user);
  const initial = (shown || "?").charAt(0).toUpperCase();
  const photo = profile?.picture ?? user.photoURL;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={labels.mypage}
        title={shown}
        className="flex h-9 w-9 items-center justify-center rounded-full border border-outline-variant bg-surface transition-colors hover:border-on-surface-variant/50"
      >
        <Avatar photoURL={photo} initial={initial} size={26} />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-lg border border-outline-variant bg-surface shadow-card-hover"
        >
          <MenuLink href="/me" label={labels.mypage} />
          <MenuLink href="/me/settings" label={labels.settings} />
          <button
            type="button"
            onClick={async () => {
              setOpen(false);
              await signOut();
            }}
            className="block w-full border-t border-outline-variant px-4 py-2.5 text-left text-body-sm text-on-surface-variant transition-colors hover:bg-surface-container hover:text-error"
          >
            {labels.logout}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function MenuLink({
  href,
  label,
}: {
  href: "/me" | "/me/settings";
  label: string;
}) {
  return (
    <Link
      href={href as Route}
      className="block px-4 py-2.5 text-body-sm text-on-surface transition-colors hover:bg-surface-container"
    >
      {label}
    </Link>
  );
}

function Avatar({
  photoURL,
  initial,
  size,
}: {
  photoURL: string | null;
  initial: string;
  size: number;
}) {
  if (photoURL) {
    return (
      <Image
        src={photoURL}
        alt=""
        width={size}
        height={size}
        className="rounded-full"
        referrerPolicy="no-referrer"
        unoptimized
      />
    );
  }
  return (
    <span
      className="flex items-center justify-center rounded-full bg-secondary text-on-secondary text-body-sm font-semibold"
      style={{ width: size, height: size }}
    >
      {initial}
    </span>
  );
}
