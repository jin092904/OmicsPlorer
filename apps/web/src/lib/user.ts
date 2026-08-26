"use client";

// Firebase Auth (Google sign-in) 기반 클라이언트 user 훅.
// 백엔드 호출 시 ID 토큰은 getIdToken() 으로 즉석에서 가져와 Authorization 헤더에 실어보냄.
import { useEffect, useState } from "react";

import {
  getFirebaseAuth,
  onAuthStateChanged,
  signInWithGoogle,
  signOut as fbSignOut,
  type FirebaseUser,
} from "./firebase";

export type AppUser = {
  id: string;
  name: string;
  email: string | null;
  photoURL: string | null;
};

function toAppUser(u: FirebaseUser): AppUser {
  return {
    id: u.uid,
    name: u.displayName || u.email || "User",
    email: u.email,
    photoURL: u.photoURL,
  };
}

export function useUser(): {
  user: AppUser | null;
  loading: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
} {
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const auth = getFirebaseAuth();
    if (!auth) {
      // Firebase 미설정 — 게스트 모드. 인증 없이 검색 가능.
      setLoading(false);
      return;
    }
    const unsub = onAuthStateChanged(auth, (fbUser) => {
      setUser(fbUser ? toAppUser(fbUser) : null);
      setLoading(false);
    });
    return () => unsub();
  }, []);

  const signIn = async () => {
    await signInWithGoogle();
  };

  const signOut = async () => {
    await fbSignOut();
  };

  return { user, loading, signIn, signOut };
}

// 백엔드 호출용 — 항상 신선한 토큰을 받기 위해 getIdToken(true) 옵션은 사용처에서 결정.
export async function getCurrentIdToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;
  const auth = getFirebaseAuth();
  if (!auth) return null;
  const u = auth.currentUser;
  if (!u) return null;
  return u.getIdToken();
}
