"use client";

// Sticky TOC — 페이지 내 섹션 anchor 링크 + 현재 보이는 섹션 하이라이트.
// IntersectionObserver 로 가시성 추적.
import { useEffect, useState } from "react";

export type TocItem = { id: string; label: string };

export function PageTOC({
  items,
  title,
}: {
  items: TocItem[];
  title: string;
}) {
  const [active, setActive] = useState<string | null>(items[0]?.id ?? null);

  useEffect(() => {
    if (typeof window === "undefined" || items.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        // 가장 위쪽에 보이는 섹션을 active 로.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0 && visible[0]) {
          setActive(visible[0].target.id);
        }
      },
      // header 가 sticky top 60px 이라 그 아래에서부터 잡히도록 -60px offset
      { rootMargin: "-72px 0px -50% 0px", threshold: 0 },
    );
    items.forEach((it) => {
      const el = document.getElementById(it.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [items]);

  return (
    <nav
      aria-label={title}
      className="sticky top-[76px] hidden flex-col rounded-xl border border-outline-variant bg-surface p-4 lg:flex"
    >
      <p className="px-2 text-label-caps uppercase text-on-surface-variant">{title}</p>
      <ul className="mt-2 flex flex-col gap-0.5">
        {items.map((it) => (
          <li key={it.id}>
            <a
              href={`#${it.id}`}
              className={`block rounded-md border-l-2 px-3 py-1.5 text-body-sm transition-colors ${
                active === it.id
                  ? "border-secondary bg-secondary-container/40 text-on-secondary-container"
                  : "border-transparent text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
              }`}
            >
              {it.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
