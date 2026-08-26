import type { T } from "@/lib/i18n";

export function Footer({ t }: { t: T }) {
  return (
    <footer className="mt-auto w-full border-t border-outline-variant bg-surface">
      <div className="mx-auto flex w-full max-w-container-max flex-col gap-3 px-6 py-7 text-body-sm text-on-surface-variant md:flex-row md:items-center md:justify-between">
        <div>
          © 2026 OmicsPlorer · {t.footer.tagline}
        </div>
        <div className="flex flex-wrap gap-5 text-body-sm">
          <a href="/.well-known/security.txt" className="hover:text-secondary transition-colors">
            {t.footer.securityTxt}
          </a>
          <span title={t.footer.comingSoon} className="opacity-50">
            {t.footer.apiDocs}
          </span>
          <span title={t.footer.comingSoon} className="opacity-50">
            {t.footer.terms}
          </span>
        </div>
      </div>
    </footer>
  );
}
