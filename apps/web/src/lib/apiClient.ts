"use client";

// 브라우저 → FastAPI 직접 호출 클라이언트.
// `getCurrentIdToken()` 으로 Firebase ID 토큰을 매 요청 시점에 가져와 Bearer 헤더에 실어보냄.
// 토큰 만료(~1h)는 firebase SDK 가 자동 refresh.
import { getCurrentIdToken } from "./user";

// `/backend` 는 next.config.mjs 의 rewrites 가 backend `/api/v1/*` 로 proxy 함.
// same-origin fetch 가 되어 CORS preflight 가 발생하지 않음.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/backend";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function authFetch(
  path: string,
  init: RequestInit = {},
  { requireAuth = false }: { requireAuth?: boolean } = {},
): Promise<Response> {
  const token = await getCurrentIdToken();
  if (requireAuth && !token) {
    // eslint-disable-next-line no-console
    console.error("[apiClient] no Firebase token available — request blocked", {
      path,
      hasWindow: typeof window !== "undefined",
    });
    throw new ApiError("not_authenticated", 401);
  }
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (init.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers, cache: "no-store" });
  } catch (e) {
    // 네트워크 에러 (CORS / DNS / fetch reject) — 무엇이든 캡처해서 남김.
    // eslint-disable-next-line no-console
    console.error("[apiClient] fetch error", { url: `${API_URL}${path}`, e });
    throw e;
  }
  if (!res.ok && (res.status === 401 || res.status >= 500)) {
    // eslint-disable-next-line no-console
    console.warn("[apiClient] non-ok response", {
      url: `${API_URL}${path}`,
      status: res.status,
    });
  }
  return res;
}

// ---------- /me ------------------------------------------------------------

export type MePrincipal = {
  uid: string;
  email: string | null;
  email_verified: boolean;
  name: string | null;
  picture: string | null;
  nickname: string | null;
  user_id: string;
  tenant_id: string;
};

export async function fetchMe(): Promise<MePrincipal> {
  const res = await authFetch("/me", {}, { requireAuth: true });
  if (!res.ok) throw new ApiError(`/me failed`, res.status);
  return (await res.json()) as MePrincipal;
}

export async function patchProfile(input: {
  nickname?: string | null;
}): Promise<MePrincipal> {
  const res = await authFetch(
    "/me/profile",
    { method: "PATCH", body: JSON.stringify(input) },
    { requireAuth: true },
  );
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json())?.detail ?? "";
    } catch {
      /* ignore */
    }
    throw new ApiError(detail || `/me/profile failed`, res.status);
  }
  return (await res.json()) as MePrincipal;
}

// ---------- /me/saved -------------------------------------------------------

export type SavedDatasetSummary = {
  dataset_id: string;
  source_db: string;
  source_id: string;
  title: string;
  modality: string[];
  organism_taxid: number[];
  saved_at: string | null;
};

export async function fetchSaved(): Promise<SavedDatasetSummary[]> {
  const res = await authFetch("/me/saved", {}, { requireAuth: true });
  if (!res.ok) throw new ApiError(`/me/saved GET failed`, res.status);
  const json = (await res.json()) as { items: SavedDatasetSummary[] };
  return json.items;
}

export async function postSaved(dataset_id: string): Promise<{ saved: boolean }> {
  const res = await authFetch(
    "/me/saved",
    { method: "POST", body: JSON.stringify({ dataset_id }) },
    { requireAuth: true },
  );
  if (!res.ok) throw new ApiError(`/me/saved POST failed`, res.status);
  return (await res.json()) as { saved: boolean };
}

export async function deleteSaved(dataset_id: string): Promise<void> {
  const res = await authFetch(
    `/me/saved/${dataset_id}`,
    { method: "DELETE" },
    { requireAuth: true },
  );
  if (!res.ok && res.status !== 404) {
    throw new ApiError(`/me/saved DELETE failed`, res.status);
  }
}
