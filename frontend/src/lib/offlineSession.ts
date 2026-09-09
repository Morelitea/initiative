/**
 * Staying signed in while there is no signal.
 *
 * `AuthProvider` bootstraps by reading the account, and a request that fails
 * used to end the session however it failed — so opening the app with no
 * connection landed on the sign-in screen and nothing cached could be reached.
 *
 * The two outcomes are told apart here:
 *
 *   * the server answered — whatever it said, that answer is used;
 *   * nothing answered — the last-known user is kept, marked **unverified**,
 *     and re-read as soon as there is signal.
 *
 * The snapshot behind the second case is thin, belongs to one server, expires
 * on the same clock as the cache it accompanies, and is erased on sign-out.
 * See `history/offline-reading-design.md`.
 */

import type { UserRead } from "@/api/generated/initiativeAPI.schemas";
import { OFFLINE_CACHE_MAX_AGE_MS } from "@/lib/offlineCache";
import { getStoredServerUrl } from "@/lib/serverStorage";
import { getItem, removeItem, setItem } from "@/lib/storage";

const SESSION_SNAPSHOT_KEY = "initiative-offline-session";
const GUILDS_SNAPSHOT_KEY = "initiative-offline-guilds";

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
 * at any deployment, and each keeps its own snapshot. Falls back to a constant
 * for a dev build with a compiled-in URL.
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
  removeItem(GUILDS_SNAPSHOT_KEY);
};

/**
 * The last-known user, if the snapshot is inside the window and belongs to the
 * server currently configured. Anything else returns null and clears the
 * snapshot on the way out.
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
 * Drawn narrowly: any response at all counts as an answer and is never read as
 * "offline". Only a request that produced no response qualifies, which is what
 * axios reports for a dropped connection, a DNS failure or a timeout.
 */
/**
 * True when the server refused the session itself.
 *
 * The companion question to {@link isNoAnswerError}, and a narrower one than
 * "did the server answer". A 500 or a 502 is an answer, but it says the server
 * is having trouble — not that this session is over. Only a 401 is the server
 * declining the credentials it was given, so only a 401 ends the session's
 * hold on anything kept for it.
 */
export const isSessionRejected = (error: unknown): boolean => {
  if (typeof error !== "object" || error === null) return false;
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return status === 401;
};

export const isNoAnswerError = (error: unknown): boolean => {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { response?: unknown; request?: unknown; code?: string };
  if (candidate.response !== undefined && candidate.response !== null) return false;
  // A request object with no response is axios's shape for "sent, nothing came
  // back"; the timeout code covers the case where it never got that far.
  return candidate.request !== undefined || candidate.code === "ECONNABORTED";
};

/**
 * The communities the app lists in its switcher.
 *
 * `GuildProvider` fetches these directly rather than through React Query, so
 * they are not part of the persisted query cache — and without them a launch
 * with no signal has an empty switcher and cannot open any of the pages it
 * still holds. Kept under the same envelope as the session above: same window,
 * same server, cleared together.
 *
 * Communities reached only by a time-bound grant are not recorded here, since
 * none of their content is cached — a way in would lead somewhere empty.
 */
export const saveOfflineGuilds = (guilds: unknown[], serverUrl: string): void => {
  try {
    setItem(GUILDS_SNAPSHOT_KEY, JSON.stringify({ guilds, savedAt: Date.now(), serverUrl }));
  } catch {
    // A convenience, never a reason to fail a load that otherwise worked.
  }
};

export const readOfflineGuilds = <T>(serverUrl: string): T[] | null => {
  const raw = getItem(GUILDS_SNAPSHOT_KEY);
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    removeItem(GUILDS_SNAPSHOT_KEY);
    return null;
  }

  const candidate = parsed as { guilds?: unknown; savedAt?: unknown; serverUrl?: unknown };
  const fresh =
    Array.isArray(candidate.guilds) &&
    typeof candidate.savedAt === "number" &&
    candidate.serverUrl === serverUrl &&
    Date.now() - candidate.savedAt <= OFFLINE_CACHE_MAX_AGE_MS;

  if (!fresh) {
    removeItem(GUILDS_SNAPSHOT_KEY);
    return null;
  }
  return candidate.guilds as T[];
};
