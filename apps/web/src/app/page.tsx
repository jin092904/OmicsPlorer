import { AppShell } from "@/components/AppShell";
import { DashboardOverview } from "@/components/DashboardOverview";
import { HeroSearch } from "@/components/HeroSearch";
import { fetchStats } from "@/lib/api";
import { getT } from "@/lib/i18n-server";

export default async function HomePage() {
  const [{ locale, t }, stats] = await Promise.all([getT(), fetchStats()]);
  return (
    <AppShell locale={locale} t={t} showSearch={false}>
      <main className="flex flex-grow flex-col">
        {/* Hero — 가벼워진 톤. 큰 제목 한 줄 + 검색창. */}
        <section className="flex w-full flex-col items-center justify-center px-6 pt-14 pb-10 text-center md:pt-20 md:pb-12">
          <p className="text-body-sm font-medium text-on-surface-variant">{t.landing.kicker}</p>
          <h1 className="mt-4 max-w-4xl text-balance text-headline-lg text-on-background">
            {t.landing.title}
          </h1>
          <p className="mt-4 max-w-2xl text-balance text-body-lg text-on-surface-variant">
            {t.landing.subtitle}
          </p>
          <div className="mt-9 w-full">
            <HeroSearch
              placeholder={t.landing.heroPlaceholder}
              submitLabel={t.landing.heroSubmit}
              tryLabel={t.landing.tryLabel}
              suggestions={t.landing.suggestions}
              tr={t.translate}
            />
          </div>
        </section>

        {/* 트렌드 / 소식 — Database at a Glance + 최근 데이터셋 + 추천 검색어 */}
        <section className="border-t border-outline-variant bg-surface-container-low px-6 py-12 md:px-8">
          <div className="mx-auto w-full max-w-5xl">
            <DashboardOverview stats={stats} locale={locale} />
          </div>
        </section>

        {/* 기능 소개 — 가장 아래로 이동, 보조 정보로 격하 */}
        <section className="px-6 py-12 md:px-8">
          <div className="mx-auto grid w-full max-w-5xl grid-cols-1 gap-5 md:grid-cols-3">
            {t.landing.features.map((feature) => (
              <article
                key={feature.heading}
                className="rounded-xl border border-outline-variant bg-surface p-6 transition-shadow hover:shadow-card"
              >
                <h3 className="text-headline-sm text-on-surface">{feature.heading}</h3>
                <p className="mt-3 text-body-md text-on-surface-variant">{feature.body}</p>
              </article>
            ))}
          </div>
        </section>
      </main>
    </AppShell>
  );
}
