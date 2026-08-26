"use client";

// 클라이언트 라우트 가드 — 비인증 시 /login?next=<현재경로> 로 redirect.
// 비로그인 SSR 페이지를 막진 못하지만 (서버는 토큰 미전달), 마이페이지는 어차피 클라이언트
// 데이터에 의존하므로 가드도 클라이언트에서 충분.
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useUser } from "@/lib/user";

export function AuthGuard({
  children,
  locale,
}: {
  children: React.ReactNode;
  locale: "ko" | "en";
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loading } = useUser();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      const next = encodeURIComponent(pathname || "/me");
      router.replace(`/login?next=${next}`);
    }
  }, [loading, user, pathname, router]);

  if (loading || !user) {
    return (
      <div
        className="flex min-h-[40vh] items-center justify-center text-body-sm text-on-surface-variant"
        aria-busy="true"
      >
        {locale === "ko" ? "로그인 정보를 확인하는 중..." : "Checking sign-in..."}
      </div>
    );
  }

  return <>{children}</>;
}
