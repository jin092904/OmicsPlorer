"use client";

// 로그인 사용자 프로필(/me) 단일 진실 원천. 닉네임 우선의 표시 이름을 산출.
//
// 모듈 캐시 + 동시 fetch 디듀프 + custom event 로 PATCH 후 자동 갱신.
// auth 상태가 바뀌면(uid 변경) 캐시 무효화.
import { useCallback, useEffect, useState } from "react";

import { fetchMe, type MePrincipal } from "./apiClient";
import { useUser, type AppUser } from "./user";

const PROFILE_REFRESH_EVENT = "genofinder:profile-refresh";

let _cached: { uid: string; profile: MePrincipal } | null = null;
let _inflight: Promise<MePrincipal> | null = null;

async function loadProfile(uid: string): Promise<MePrincipal> {
  if (_cached && _cached.uid === uid) return _cached.profile;
  if (_inflight) return _inflight;
  _inflight = fetchMe()
    .then((p) => {
      _cached = { uid, profile: p };
      return p;
    })
    .finally(() => {
      _inflight = null;
    });
  return _inflight;
}

export function invalidateProfile(): void {
  _cached = null;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(PROFILE_REFRESH_EVENT));
  }
}

export function useProfile(): {
  profile: MePrincipal | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
} {
  const { user, loading: authLoading } = useUser();
  const [profile, setProfile] = useState<MePrincipal | null>(
    _cached && user && _cached.uid === user.id ? _cached.profile : null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!user) {
      setProfile(null);
      return;
    }
    setLoading(true);
    try {
      const p = await loadProfile(user.id);
      setProfile(p);
      setError(null);
    } catch (e) {
      setError((e as Error).message || "profile fetch failed");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      _cached = null;
      setProfile(null);
      return;
    }
    void refresh();
  }, [authLoading, user, refresh]);

  // 다른 컴포넌트가 invalidateProfile() 호출하면 동기 갱신.
  useEffect(() => {
    const handle = () => {
      void refresh();
    };
    window.addEventListener(PROFILE_REFRESH_EVENT, handle);
    return () => window.removeEventListener(PROFILE_REFRESH_EVENT, handle);
  }, [refresh]);

  return { profile, loading: authLoading || loading, error, refresh };
}

// 표시 이름 우선순위:
//   nickname (사용자가 직접 정한 별명)
//   → name (Firebase displayName)
//   → email local-part
//   → "User"
export function displayNameOf(
  profile: MePrincipal | null,
  user: AppUser | null,
): string {
  const candidate =
    profile?.nickname?.trim() ||
    profile?.name?.trim() ||
    user?.name?.trim() ||
    (profile?.email || user?.email || "").split("@")[0] ||
    "User";
  return candidate;
}
