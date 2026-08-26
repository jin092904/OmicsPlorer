"use client";

// 데이터셋 상세 → 검색결과 복귀. 사용자 결정(2026-06-12): 브라우저 뒤로가기 방식.
// 직전 페이지가 같은 출처(검색결과 등 내부)면 history.back() 으로 쿼리·필터·페이지·스크롤
// 까지 그대로 복원. 외부에서 직접 들어온 경우(referrer 없음/다른 도메인)엔 /search 폴백.

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export function BackButton({ label, fallbackHref = "/search" }: { label: string; fallbackHref?: string }) {
  const router = useRouter();
  const [canGoBack, setCanGoBack] = useState(false);

  useEffect(() => {
    // 같은 사이트 내부에서 넘어온 경우에만 history.back 이 검색결과로 안전 복귀.
    try {
      const ref = document.referrer;
      const sameOrigin = ref ? new URL(ref).origin === window.location.origin : false;
      setCanGoBack(sameOrigin && window.history.length > 1);
    } catch {
      setCanGoBack(false);
    }
  }, []);

  const onClick = (e: React.MouseEvent) => {
    if (canGoBack) {
      e.preventDefault();
      router.back();
    }
    // canGoBack=false 면 기본 <a href> 동작(fallbackHref)으로 진행.
  };

  return (
    <a
      href={fallbackHref}
      onClick={onClick}
      className="text-body-sm font-medium text-secondary transition-opacity hover:opacity-70"
    >
      {label}
    </a>
  );
}
