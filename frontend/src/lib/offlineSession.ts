/**
 * Being signed in while there is no signal.
 *
 * Persisting the query cache alone achieves nothing: opening the app offline
 * fails before any of it matters, because `AuthProvider` bootstraps by calling
 * `/users/me`, and today a network failure and a rejection are handled
 * identically — the user is cleared and the route guard bounces to the login
 * screen. You cannot read offline because you cannot *be* signed in offline.
 *
 * So the two failures have to be told apart:
 *
 *   * the server answered (`401`, or anything else) — the session is genuinely
 *     over, so sign out and purge;
 *   * nothing answered — we could not ask, so keep the last-known user, marked
 *     **unverified**, and re-verify the moment there is signal again.
 *
 * The snapshot that makes the second case possible is deliberately thin, bound
 * to one server, expires on the same clock as the cache it accompanies, and is
 * erased on sign-out. See `history/offline-reading-design.md`.
 */

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { OFFLINE_CACHE_MAX_AGE_MS } from "@/lib/offlineCache";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, removeItem, setItem } from "@/lib/storage";

const SESSION_SNAPSHOT_KEY = "initiative-offline-session";

interface SessionSnapshot {
  user: UserRead;
  /** Epoch ms. The snapshot expires on the same clock as the cache. */
  savedAt: number;
  /** The server this identity belongs to; a different one is a different app. */
  serverUrl: string;
}

const isSnapshot = (value: unknown): value is SessionSnapshot => {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<SessionSnapshot>;
  return (
    typeof candidate.savedAt === "number" &&
    typeof candidate.serverUrl === "string" &&
    typeof candidate.user === "object" &&
    candidate.user !== null &&
    typeof (candidate.user as UserRead).id === "number"
  );
};

/**
 * Which server this identity and cache belong to. The native app can be pointed
 * at any deployment, and one server's snapshot must never be offered to
 * another. Falls back to a constant for a dev build with a compiled-in URL.
 */
export const currentServerKey = (): string => getStoredServerUrl() ?? "default";

/** Record who is signed in, so a later cold start with no signal can say so. */
export const saveOfflineSession = (user: UserRead, serverUrl: string): void => {
  try {
    const snapshot: SessionSnapshot = { user, savedAt: Date.now(), serverUrl };
    setItem(SESSION_SNAPSHOT_KEY, JSON.stringify(snapshot));
  } catch {
    // Storage refused. Offline reading is a convenience — never a reason to
    // fail a sign-in that has otherwise succeeded.
  }
};

export const clearOfflineSession = (): void => {
  removeItem(SESSION_SNAPSHOT_KEY);
};

/**
 * The last-known user, if the snapshot is inside the window and belongs to the
 * server currently configured. Anything else returns null and takes the
 * snapshot with it, so a stale one cannot be reconsidered later.
 */
export const readOfflineSession = (serverUrl: string): UserRead | null => {
  const raw = getItem(SESSION_SNAPSHOT_KEY);
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    clearOfflineSession();
    return null;
  }

  if (!isSnapshot(parsed)) {
    clearOfflineSession();
    return null;
  }
  if (parsed.serverUrl !== serverUrl) {
    clearOfflineSession();
    return null;
  }
  if (Date.now() - parsed.savedAt > OFFLINE_CACHE_MAX_AGE_MS) {
    clearOfflineSession();
    return null;
  }

  return parsed.user;
};

/**
 * True when a request failed without the server saying anything.
 *
 * The distinction this draws is the whole safety property, so it is drawn
 * narrowly: an answer of any kind — including a `401` — is the server speaking,
 * and is never treated as "offline". Only a request that produced no response
 * at all qualifies, which is what axios reports for a dropped connection, a
 * DNS failure or a timeout.
 */
export const isNoAnswerError = (error: unknown): boolean => {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { response?: unknown; request?: unknown; code?: string };
  if (candidate.response !== undefined && candidate.response !== null) return false;
  // A request object with no response is axios's shape for "sent, nothing came
  // back"; the timeout code covers the case where it never got that far.
  return candidate.request !== undefined || candidate.code === "ECONNABORTED";
};
