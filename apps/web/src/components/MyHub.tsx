"use client";

import type { Route } from "next";
import Image from "next/image";
import Link from "next/link";

import { useRecentlyViewed, useSavedDatasets } from "@/lib/datasetMemory";
import { displayNameOf, useProfile } from "@/lib/useProfile";
import { useUser } from "@/lib/user";

export function MyHub({ locale }: { locale: "ko" | "en" }) {
  const { user, signOut } = useUser();
  const { profile: me, error: profileError } = useProfile();
  const { items: saved } = useSavedDatasets();
  const { items: recent } = useRecentlyViewed();

  const meError = profileError
    ? locale === "ko"
      ? "프로필을 불러오지 못했습니다."
      : "Failed to load profile."
    : null;

  const labels =
    locale === "ko"
      ? {
          welcome: "환영합니다",
          displayedAs: "표시 이름",
          settings: "프로필 / 설정",
          settingsDesc: "닉네임, 언어, 테마를 변경할 수 있습니다.",
          saved: "찜한 데이터셋",
          savedDesc: "기기 간에 자동으로 동기화됩니다.",
          recent: "최근 본 데이터셋",
          recentDesc: "이 브라우저에서 최근에 본 데이터셋입니다.",
          community: "커뮤니티",
          communityDesc: "곧 공개됩니다. 커뮤니티에서는 닉네임으로 표시됩니다.",
          comingSoon: "준비 중",
          signOut: "로그아웃",
          go: "열기 →",
        }
      : {
          welcome: "Welcome",
          displayedAs: "Shown as",
          settings: "Profile & Settings",
          settingsDesc: "Change nickname, language, and theme.",
          saved: "Saved datasets",
          savedDesc: "Synced bookmarks across your devices.",
          recent: "Recently viewed",
          recentDesc: "Recent items from this browser.",
          community: "Community",
          communityDesc: "Coming soon. You’ll be identified by your nickname.",
          comingSoon: "Coming soon",
          signOut: "Sign out",
          go: "Open →",
        };

  if (!user) return null;

  const shown = displayNameOf(me, user);
  const photo = me?.picture ?? user.photoURL;

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-4 rounded-xl border border-outline-variant bg-surface p-6 sm:flex-row sm:items-center sm:gap-6">
        <Avatar photoURL={photo} initial={(shown || "?").charAt(0).toUpperCase()} size={64} />
        <div className="min-w-0 flex-1">
          <p className="text-body-sm uppercase tracking-wider text-on-surface-variant">
            {labels.welcome}
          </p>
          <h1 className="mt-1 text-headline-md text-on-surface">{shown}</h1>
          {me?.email ? (
            <p className="mt-1 truncate text-body-sm text-on-surface-variant">{me.email}</p>
          ) : null}
          {me?.nickname ? (
            <p className="mt-2 inline-flex items-center gap-2 rounded-md bg-secondary-container/60 px-2.5 py-1 text-body-sm text-on-secondary-container">
              <span className="text-label-caps uppercase opacity-70">{labels.displayedAs}</span>
              <span className="font-medium">{me.nickname}</span>
            </p>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => void signOut()}
          className="self-start rounded-md border border-outline-variant px-3.5 py-2 text-body-sm font-medium text-on-surface-variant transition-colors hover:border-error/40 hover:text-error sm:self-center"
        >
          {labels.signOut}
        </button>
      </header>

      {meError ? (
        <p className="rounded-md border border-error/40 bg-error-container/40 px-4 py-2.5 text-body-sm text-on-error-container">
          {meError}
        </p>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2">
        <HubCard
          href="/me/settings"
          title={labels.settings}
          desc={labels.settingsDesc}
          ctaLabel={labels.go}
        />
        <HubCard
          href="/me/saved"
          title={labels.saved}
          desc={labels.savedDesc}
          count={saved.length}
          ctaLabel={labels.go}
        />
        <HubCard
          href="/me/recent"
          title={labels.recent}
          desc={labels.recentDesc}
          count={recent.length}
          ctaLabel={labels.go}
        />
        <HubCard
          title={labels.community}
          desc={labels.communityDesc}
          ctaLabel={labels.comingSoon}
          disabled
        />
      </section>
    </div>
  );
}

function HubCard({
  href,
  title,
  desc,
  count,
  ctaLabel,
  disabled = false,
}: {
  href?: Route;
  title: string;
  desc: string;
  count?: number;
  ctaLabel: string;
  disabled?: boolean;
}) {
  const inner = (
    <div className="flex h-full flex-col rounded-xl border border-outline-variant bg-surface p-5 transition-shadow hover:shadow-card-hover">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-headline-sm text-on-surface">{title}</h2>
        {typeof count === "number" ? (
          <span className="font-mono text-mono-data text-on-surface-variant">{count}</span>
        ) : null}
      </div>
      <p className="mt-2 text-body-sm text-on-surface-variant">{desc}</p>
      <span
        className={`mt-5 inline-block text-body-sm font-medium ${
          disabled ? "text-on-surface-variant/50" : "text-secondary"
        }`}
      >
        {ctaLabel}
      </span>
    </div>
  );

  if (disabled || !href) {
    return <div className="cursor-not-allowed opacity-80">{inner}</div>;
  }
  return <Link href={href}>{inner}</Link>;
}

function Avatar({
  photoURL,
  initial,
  size,
}: {
  photoURL: string | null | undefined;
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
      className="flex shrink-0 items-center justify-center rounded-full bg-secondary text-on-secondary"
      style={{ width: size, height: size, fontSize: size / 2.4 }}
    >
      {initial}
    </span>
  );
}
