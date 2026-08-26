"use client";

import { useNavigation } from "@/components/NavigationPending";
import { LOCALE_COOKIE, type Locale } from "@/lib/i18n";

export function LanguageToggle({
  currentLocale,
  switchToLabel,
  ariaLabel,
}: {
  currentLocale: Locale;
  switchToLabel: string;
  ariaLabel: string;
}) {
  const { refresh } = useNavigation();
  const next: Locale = currentLocale === "ko" ? "en" : "ko";

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={() => {
        document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
        refresh();
      }}
      className="flex h-9 min-w-[2.75rem] items-center justify-center rounded-md border border-outline-variant bg-surface px-3 text-body-sm font-medium text-on-surface-variant transition-colors hover:border-on-surface-variant/50 hover:text-on-surface"
      title={ariaLabel}
    >
      {switchToLabel}
    </button>
  );
}
