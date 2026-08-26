"use client";

// 모바일(< md) 슬라이드-인 drawer. 햄버거 버튼은 Header 안에 있고,
// 본 컴포넌트는 backdrop + Sidebar(mobileDrawerMode) 를 함께 렌더한다.
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import type { Locale, T } from "@/lib/i18n";

import { Sidebar } from "./Sidebar";

export function MobileNav({
  locale,
  t,
}: {
  locale: Locale;
  t: T;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // 라우트 변경 시 자동 닫기
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // body 스크롤 잠금
  useEffect(() => {
    if (typeof document === "undefined") return;
    if (open) {
      const prev = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = prev;
      };
    }
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={locale === "ko" ? "메뉴 열기" : "Open menu"}
        className="flex h-9 w-9 items-center justify-center rounded-md border border-outline-variant bg-surface text-on-surface-variant transition-colors hover:border-on-surface-variant/50 hover:text-on-surface md:hidden"
      >
        <MenuIcon />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-[80] md:hidden"
          onClick={(e) => {
            if (e.target === e.currentTarget) setOpen(false);
          }}
        >
          <div className="absolute inset-0 bg-on-surface/40 backdrop-blur-sm" />
          <div className="relative h-full w-72 max-w-[85vw] animate-[slideIn_180ms_ease-out] shadow-xl">
            <Sidebar
              locale={locale}
              t={t}
              initialState="expanded"
              mobileDrawerMode
              onCloseMobile={() => setOpen(false)}
            />
          </div>
        </div>
      ) : null}

      <style jsx global>{`
        @keyframes slideIn {
          from {
            transform: translateX(-100%);
          }
          to {
            transform: translateX(0);
          }
        }
      `}</style>
    </>
  );
}

function MenuIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}
