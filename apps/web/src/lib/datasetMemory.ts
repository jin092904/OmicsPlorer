"use client";

// 최근 본 데이터셋  → localStorage 단독 (정보 가치가 일시적, 서버 동기 필요 없음).
// 찜 데이터셋     → 로그인 시 서버(/me/saved) 동기, 비로그인 시 localStorage.
//                  최초 로그인 1회 한정으로 localStorage → 서버 마이그레이션.
import { useCallback, useEffect, useRef, useState } from "react";

import { deleteSaved, fetchSaved, postSaved, type SavedDatasetSummary } from "./apiClient";
import { useUser } from "./user";

const RECENT_KEY = "genofinder.recent.v1";
const SAVED_KEY = "genofinder.saved.v1";
const MIGRATED_PREFIX = "genofinder.saved.migrated.";

export type DatasetMemoryEntry = {
  dataset_id: string;
  source_db: string;
  source_id: string;
  title: string | null;
  modality: string[];
  organism_taxid: number[];
  ts: number;
};

const RECENT_LIMIT = 20;

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------
function safeRead(key: string): DatasetMemoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as DatasetMemoryEntry[]) : [];
  } catch {
    return [];
  }
}

function safeWrite(key: string, items: DatasetMemoryEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(items));
    window.dispatchEvent(new CustomEvent(`genofinder:${key}-change`));
  } catch {
    /* quota 등 무시 */
  }
}

function fromSummary(s: SavedDatasetSummary): DatasetMemoryEntry {
  return {
    dataset_id: s.dataset_id,
    source_db: s.source_db,
    source_id: s.source_id,
    title: s.title,
    modality: s.modality,
    organism_taxid: s.organism_taxid,
    ts: s.saved_at ? Date.parse(s.saved_at) : Date.now(),
  };
}

function useLocalList(key: string): {
  items: DatasetMemoryEntry[];
  setItems: (next: DatasetMemoryEntry[]) => void;
} {
  const [items, setItems] = useState<DatasetMemoryEntry[]>([]);

  useEffect(() => {
    setItems(safeRead(key));
    const handler = () => setItems(safeRead(key));
    window.addEventListener(`genofinder:${key}-change`, handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener(`genofinder:${key}-change`, handler);
      window.removeEventListener("storage", handler);
    };
  }, [key]);

  return {
    items,
    setItems: (next: DatasetMemoryEntry[]) => {
      safeWrite(key, next);
      setItems(next);
    },
  };
}

// ---------------------------------------------------------------------------
// useRecentlyViewed — localStorage 단독
// ---------------------------------------------------------------------------
export function useRecentlyViewed(): {
  items: DatasetMemoryEntry[];
  record: (entry: Omit<DatasetMemoryEntry, "ts">) => void;
  clear: () => void;
} {
  const { items } = useLocalList(RECENT_KEY);
  const record = useCallback(
    (entry: Omit<DatasetMemoryEntry, "ts">) => {
      const now = Date.now();
      const current = safeRead(RECENT_KEY);
      const without = current.filter((it) => it.dataset_id !== entry.dataset_id);
      const next = [{ ...entry, ts: now }, ...without].slice(0, RECENT_LIMIT);
      safeWrite(RECENT_KEY, next);
    },
    [],
  );
  const clear = useCallback(() => safeWrite(RECENT_KEY, []), []);
  return { items, record, clear };
}

// ---------------------------------------------------------------------------
// 서버-동기 saved 캐시 — 모듈 단위 1개. 모든 useSavedDatasets() 인스턴스가 공유.
//
// 패턴: useProfile.ts 와 동일 — 모듈 캐시 + custom event 로 인스턴스간 동기.
// 토글 한 번에 N 개 컴포넌트가 동시에 갱신되도록.
// ---------------------------------------------------------------------------
const SAVED_SERVER_CHANGE = "genofinder:saved-server-change";

let _savedCache: { uid: string; items: DatasetMemoryEntry[] } | null = null;
let _savedInflight: Promise<DatasetMemoryEntry[]> | null = null;

function broadcastSaved(uid: string, items: DatasetMemoryEntry[]): void {
  _savedCache = { uid, items };
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(SAVED_SERVER_CHANGE));
  }
}

function dropSavedCache(): void {
  _savedCache = null;
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(SAVED_SERVER_CHANGE));
  }
}

// Optimistic 실패 시 부분 revert. 전체 cache 를 closure 의 stale 값으로 대체하지 않고
// 해당 dataset_id 만 더하거나 빼서 동시 다른 toggle 의 효과를 보존.
function revertOptimisticAdd(uid: string, dataset_id: string): void {
  if (_savedCache?.uid !== uid) return;
  broadcastSaved(
    uid,
    _savedCache.items.filter((it) => it.dataset_id !== dataset_id),
  );
}

function revertOptimisticRemove(uid: string, entry: DatasetMemoryEntry): void {
  if (_savedCache?.uid !== uid) return;
  if (_savedCache.items.some((it) => it.dataset_id === entry.dataset_id)) return;
  broadcastSaved(uid, [entry, ..._savedCache.items]);
}

async function loadSavedFromServer(uid: string): Promise<DatasetMemoryEntry[]> {
  if (_savedCache && _savedCache.uid === uid) return _savedCache.items;
  if (_savedInflight) return _savedInflight;
  _savedInflight = (async () => {
    try {
      const fresh = await fetchSaved();
      const items = fresh.map(fromSummary);
      // CRITICAL: fetch 중에 사용자가 toggle 했을 수 있음. 그 사이 broadcast 가
      // _savedCache 를 채웠으면 서버 응답이 더 stale 함 → 덮어쓰지 말고 캐시 우선.
      // 빈 cache 일 때만 fetch 결과로 캐시를 채운다.
      if (!_savedCache || _savedCache.uid !== uid) {
        _savedCache = { uid, items };
        return items;
      }
      // fetch 중 toggle 발생 → 서버목록을 통째로 버리면 찜이 "방금 누른 1건"으로 쪼그라듦(레이스).
      // 서버목록(base) + 캐시(낙관적 변경)를 dataset_id union 으로 병합해 데이터 손실 방지.
      // (낙관적 remove 는 다음 액션에서 서버 진실로 정정됨 — 손실보다 안전) 2026-07-03 버그픽스.
      const cachedIds = new Set(_savedCache.items.map((it) => it.dataset_id));
      const merged = [
        ..._savedCache.items,
        ...items.filter((it) => !cachedIds.has(it.dataset_id)),
      ];
      _savedCache = { uid, items: merged };
      return merged;
    } finally {
      _savedInflight = null;
    }
  })();
  return _savedInflight;
}

// ---------------------------------------------------------------------------
// useSavedDatasets — 로그인 시 서버 동기 (공유 캐시), 비로그인 시 localStorage
// ---------------------------------------------------------------------------
export function useSavedDatasets(): {
  items: DatasetMemoryEntry[];
  isSaved: (id: string) => boolean;
  toggle: (entry: Omit<DatasetMemoryEntry, "ts">) => void;
  remove: (id: string) => void;
  clear: () => void;
  syncing: boolean;
} {
  const { user, loading } = useUser();
  const local = useLocalList(SAVED_KEY);
  const [serverItems, setServerItems] = useState<DatasetMemoryEntry[] | null>(
    user && _savedCache && _savedCache.uid === user.id ? _savedCache.items : null,
  );
  const [syncing, setSyncing] = useState(false);
  const migrationRunRef = useRef<string | null>(null);

  // 로그인 상태가 결정되면 서버 데이터 fetch (+ 1회 마이그레이션).
  useEffect(() => {
    if (loading) return;
    if (!user) {
      setServerItems(null);
      _savedCache = null;
      return;
    }

    let cancelled = false;
    const run = async () => {
      setSyncing(true);
      try {
        // 최초 1회 로컬 → 서버 마이그레이션.
        const flagKey = `${MIGRATED_PREFIX}${user.id}`;
        if (
          migrationRunRef.current !== user.id &&
          window.localStorage.getItem(flagKey) === null
        ) {
          migrationRunRef.current = user.id;
          const localItems = safeRead(SAVED_KEY);
          for (const it of localItems) {
            try {
              await postSaved(it.dataset_id);
            } catch {
              /* 이미 다른 기기에서 동기되어 있을 수 있음 — best effort */
            }
          }
          window.localStorage.setItem(flagKey, "1");
          // 이관 완료 → 로컬 찜을 비운다. (찜은 이제 계정 소유. 안 비우면 로그아웃 시
          //  옛 로컬 스냅샷이 서버 진실과 모순되게 부활함. 2026-07-03 버그픽스)
          safeWrite(SAVED_KEY, []);
        }

        const items = await loadSavedFromServer(user.id);
        if (cancelled) return;
        setServerItems(items);
      } catch {
        if (!cancelled) setServerItems([]);
      } finally {
        if (!cancelled) setSyncing(false);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [user, loading]);

  // 다른 인스턴스의 mutation 알림 → 로컬 state 동기.
  useEffect(() => {
    if (!user) return;
    const handler = () => {
      if (_savedCache && _savedCache.uid === user.id) {
        setServerItems(_savedCache.items);
      } else {
        setServerItems(null);
      }
    };
    window.addEventListener(SAVED_SERVER_CHANGE, handler);
    return () => window.removeEventListener(SAVED_SERVER_CHANGE, handler);
  }, [user]);

  const isLoggedIn = !!user && !loading;
  const items = isLoggedIn ? (serverItems ?? []) : local.items;

  const isSaved = useCallback(
    (id: string) => items.some((it) => it.dataset_id === id),
    [items],
  );

  const toggle = useCallback(
    (entry: Omit<DatasetMemoryEntry, "ts">) => {
      if (isLoggedIn && user) {
        const current = serverItems ?? [];
        const found = current.find((it) => it.dataset_id === entry.dataset_id);
        if (found) {
          // optimistic remove
          broadcastSaved(
            user.id,
            current.filter((it) => it.dataset_id !== entry.dataset_id),
          );
          deleteSaved(entry.dataset_id).catch((err) => {
            // 상세 디버그 로그 — 사용자가 풀린다고 느끼는 원인 추적용.
            // eslint-disable-next-line no-console
            console.error("[saved] DELETE failed, reverting:", err);
            revertOptimisticRemove(user.id, found);
          });
        } else {
          const newEntry = { ...entry, ts: Date.now() };
          broadcastSaved(user.id, [newEntry, ...current]);
          postSaved(entry.dataset_id).catch((err) => {
            // eslint-disable-next-line no-console
            console.error("[saved] POST failed, reverting:", err);
            revertOptimisticAdd(user.id, entry.dataset_id);
          });
        }
        return;
      }
      const cur = local.items;
      const found = cur.find((it) => it.dataset_id === entry.dataset_id);
      if (found) {
        local.setItems(cur.filter((it) => it.dataset_id !== entry.dataset_id));
      } else {
        local.setItems([{ ...entry, ts: Date.now() }, ...cur]);
      }
    },
    [isLoggedIn, user, local, serverItems],
  );

  const remove = useCallback(
    (id: string) => {
      if (isLoggedIn && user) {
        const current = serverItems ?? [];
        const removed = current.find((it) => it.dataset_id === id);
        broadcastSaved(
          user.id,
          current.filter((it) => it.dataset_id !== id),
        );
        deleteSaved(id).catch(() => {
          if (removed) revertOptimisticRemove(user.id, removed);
        });
        return;
      }
      local.setItems(local.items.filter((it) => it.dataset_id !== id));
    },
    [isLoggedIn, user, local, serverItems],
  );

  const clear = useCallback(() => {
    if (isLoggedIn && user) {
      const current = serverItems ?? [];
      broadcastSaved(user.id, []);
      Promise.all(current.map((it) => deleteSaved(it.dataset_id))).catch(() => {
        // 부분 실패 — 다음 fetch 에서 reconcile.
        dropSavedCache();
      });
      return;
    }
    local.setItems([]);
  }, [isLoggedIn, user, local, serverItems]);

  return { items, isSaved, toggle, remove, clear, syncing };
}
