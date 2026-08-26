"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useUser } from "@/lib/user";

export function LoginPanel({
  locale,
  next,
}: {
  locale: "ko" | "en";
  next: string;
}) {
  const router = useRouter();
  const { user, loading, signIn } = useUser();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 이미 로그인된 상태로 /login 진입 시 next 로 즉시 이동.
  useEffect(() => {
    if (!loading && user) {
      router.replace(next as Route);
    }
  }, [loading, user, next, router]);

  const labels =
    locale === "ko"
      ? {
          google: "Google 계정으로 계속하기",
          working: "로그인 중...",
          failed: "로그인에 실패했습니다. 잠시 후 다시 시도해주세요.",
          popupBlocked: "팝업이 차단되었습니다. 브라우저 설정을 확인해주세요.",
          alreadySignedIn: "이미 로그인되어 있습니다.",
        }
      : {
          google: "Continue with Google",
          working: "Signing in...",
          failed: "Sign-in failed. Please try again.",
          popupBlocked: "Pop-up blocked. Please check your browser settings.",
          alreadySignedIn: "You are already signed in.",
        };

  const handleGoogle = async () => {
    setError(null);
    setBusy(true);
    try {
      await signIn();
      router.replace(next as Route);
    } catch (e: unknown) {
      const code = (e as { code?: string })?.code ?? "";
      if (code === "auth/popup-blocked" || code === "auth/popup-closed-by-user") {
        setError(labels.popupBlocked);
      } else {
        setError(labels.failed);
      }
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="h-12 animate-pulse rounded-md bg-surface-container/60" />;
  }

  if (user) {
    return (
      <p className="rounded-md border border-outline-variant bg-surface-container-low px-4 py-3 text-body-sm text-on-surface-variant">
        {labels.alreadySignedIn}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        type="button"
        onClick={handleGoogle}
        disabled={busy}
        className="flex w-full items-center justify-center gap-3 rounded-md border border-outline-variant bg-surface px-4 py-3 text-body-md font-medium text-on-surface transition-colors hover:bg-surface-container disabled:cursor-not-allowed disabled:opacity-60"
      >
        <GoogleIcon />
        <span>{busy ? labels.working : labels.google}</span>
      </button>
      {error ? (
        <p className="text-body-sm text-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 0 1-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.964 10.707A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.707V4.961H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.039l3.007-2.332z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.961l3.007 2.332C4.672 5.166 6.656 3.58 9 3.58z"
      />
    </svg>
  );
}
