"use client";

import { useEffect, useRef, useState } from "react";

import { patchProfile } from "@/lib/apiClient";
import { type Locale } from "@/lib/i18n";
import { invalidateProfile, useProfile } from "@/lib/useProfile";
import { useTheme } from "@/lib/useTheme";

const NICKNAME_MAX = 32;

export function SettingsForm({ locale }: { locale: Locale }) {
  const { profile: me, loading: profileLoading, error: profileError } = useProfile();
  const { theme, setTheme, isDark } = useTheme();

  const [nickname, setNickname] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const initialized = useRef(false);
  const loading = profileLoading && !initialized.current;

  // 첫 프로필 도착 시 한 번만 input 초기화. 이후 me 갱신은 무시 — 사용자 입력 보호.
  useEffect(() => {
    if (me && !initialized.current) {
      setNickname(me.nickname ?? "");
      initialized.current = true;
    }
  }, [me]);

  useEffect(() => {
    if (profileError)
      setError(
        locale === "ko"
          ? "프로필을 불러오지 못했습니다."
          : "Failed to load profile.",
      );
  }, [profileError, locale]);

  const labels =
    locale === "ko"
      ? {
          profile: "프로필",
          nickname: "닉네임",
          nicknameHint: `최대 ${NICKNAME_MAX}자까지 입력할 수 있습니다. 비워 두면 이름이나 이메일이 대신 표시됩니다.`,
          nicknamePlaceholder: "공개 표시 이름 (선택)",
          save: "저장",
          saving: "저장 중...",
          saved: "저장되었습니다",
          appearance: "화면 표시",
          language: "언어",
          theme: "테마",
          themeLight: "밝게",
          themeDark: "어둡게",
          themeSystem: "시스템",
          systemHint: "시스템 설정에 따릅니다",
          currentDark: "현재 어두운 테마로 표시 중입니다",
          currentLight: "현재 밝은 테마로 표시 중입니다",
          loadFailed: "프로필을 불러오지 못했습니다.",
          patchFailed: "저장에 실패했습니다.",
        }
      : {
          profile: "Profile",
          nickname: "Nickname",
          nicknameHint: `Up to ${NICKNAME_MAX} characters. If blank, your display name (or email) is used.`,
          nicknamePlaceholder: "Public display name (optional)",
          save: "Save",
          saving: "Saving...",
          saved: "Saved",
          appearance: "Appearance",
          language: "Language",
          theme: "Theme",
          themeLight: "Light",
          themeDark: "Dark",
          themeSystem: "System",
          systemHint: "Follows your operating system",
          currentDark: "Dark theme is currently active",
          currentLight: "Light theme is currently active",
          loadFailed: "Failed to load profile.",
          patchFailed: "Save failed.",
        };

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const next = await patchProfile({ nickname });
      setNickname(next.nickname ?? "");
      setSavedAt(Date.now());
      // 다른 컴포넌트(UserMenu, MyHub) 의 useProfile 캐시 갱신.
      invalidateProfile();
    } catch (e) {
      const detail = (e as { message?: string })?.message ?? "";
      setError(detail || labels.patchFailed);
    } finally {
      setSaving(false);
    }
  };

  const dirty = (me?.nickname ?? "") !== nickname;

  return (
    <div className="flex flex-col gap-8">
      {/* ---------- Profile ---------- */}
      <section className="rounded-xl border border-outline-variant bg-surface p-6">
        <h2 className="text-headline-sm text-on-surface">{labels.profile}</h2>

        <label className="mt-5 block">
          <span className="text-body-sm font-medium text-on-surface">{labels.nickname}</span>
          <input
            type="text"
            value={nickname}
            onChange={(e) => setNickname(e.target.value.slice(0, NICKNAME_MAX))}
            placeholder={labels.nicknamePlaceholder}
            disabled={loading}
            className="mt-2 w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-body-md text-on-surface transition-colors placeholder:text-on-surface-variant/60 focus:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary/20 disabled:opacity-60"
            maxLength={NICKNAME_MAX}
          />
          <span className="mt-1.5 block text-body-sm text-on-surface-variant">
            {labels.nicknameHint}
          </span>
        </label>

        <div className="mt-5 flex items-center gap-3">
          <button
            type="button"
            disabled={!dirty || saving || loading}
            onClick={() => void handleSave()}
            className="rounded-md bg-secondary px-4 py-2 text-body-sm font-medium text-on-secondary transition-colors hover:bg-secondary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? labels.saving : labels.save}
          </button>
          {savedAt && !dirty && !error ? (
            <span className="text-body-sm text-on-surface-variant" aria-live="polite">
              ✓ {labels.saved}
            </span>
          ) : null}
          {error ? (
            <span className="text-body-sm text-error" role="alert">
              {error}
            </span>
          ) : null}
        </div>
      </section>

      {/* ---------- Appearance: Theme ---------- */}
      {/* 언어 세그먼트 제거 — 영어 UI 고정(2026-07-03). */}
      <section className="rounded-xl border border-outline-variant bg-surface p-6">
        <h2 className="text-headline-sm text-on-surface">{labels.appearance}</h2>

        <div className="mt-5">
          <p className="text-body-sm font-medium text-on-surface">{labels.theme}</p>
          <div className="mt-2 inline-flex flex-wrap rounded-md border border-outline-variant bg-surface-container-low p-1">
            <SegmentButton
              active={theme === "light"}
              onClick={() => setTheme("light")}
              label={labels.themeLight}
            />
            <SegmentButton
              active={theme === "dark"}
              onClick={() => setTheme("dark")}
              label={labels.themeDark}
            />
            <SegmentButton
              active={theme === "system"}
              onClick={() => setTheme("system")}
              label={labels.themeSystem}
            />
          </div>
          <p className="mt-2 text-body-sm text-on-surface-variant">
            {theme === "system"
              ? labels.systemHint
              : isDark
                ? labels.currentDark
                : labels.currentLight}
          </p>
        </div>
      </section>
    </div>
  );
}
function SegmentButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded px-3.5 py-1.5 text-body-sm font-medium transition-colors ${
        active
          ? "bg-surface text-on-surface shadow-card"
          : "text-on-surface-variant hover:text-on-surface"
      }`}
    >
      {label}
    </button>
  );
}
