/**
 * What a phone with no signal still shows: the read-only content it last
 * loaded, kept for a day.
 *
 * How the cache behaves, in four rules. The reasoning behind each is in
 * `history/offline-reading-design.md`.
 *
 *   1. It is only ever read when the device cannot reach the server. Online,
 *      every query still goes out and the server's answer is the one used;
 *      `staleTime` stays 0, so restored data refetches as soon as there is
 *      signal.
 *   2. It expires on a fixed clock.
 *   3. It belongs to one user on one server, and is erased when either changes
 *      or the user signs out.
 *   4. It holds only read-only content: default deny, an allowlist of paths,
 *      and a denylist over the top of that.
 */

import { Capacitor } from "@capacitor/core";
import { createAsyncStoragePersister } from "@tanstack/query-async-storage-persister";
import type { Query } from "@tanstack/react-query";

import { createIdbStore } from "@/lib/idbStore";
import { getItem, removeItem, setItem } from "@/lib/storage";

/**
 * How long the persisted cache lives on disk.
 *
 * A day: short enough that "removed from the initiative on Tuesday, still
 * reading it on Friday" cannot happen, long enough that a basement, a flight or
 * a bad building is still covered. It sits well inside the 30-day refresh TTL,
 * so the device never shows content it could not re-fetch if it *were* online.
 */
export const OFFLINE_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * Bumped when the shape of what we persist changes in a way that would make an
 * older blob misleading rather than merely stale. Part of the buster, so a bump
 * discards every existing cache instead of half-reading it.
 */
const OFFLINE_CACHE_SCHEMA_VERSION = 1;

/**
 * When the cache was last written — i.e. the last moment this device was online
 * with a confirmed session. Kept as its own small value rather than read back
 * out of the blob, so the banner can ask for it synchronously at render.
 */
const SYNCED_AT_KEY = "initiative-offline-synced-at";

const IDB_NAME = "initiative-offline";
const IDB_STORE = "query-cache";
const IDB_KEY = "react-query";

/**
 * Read-only content surfaces worth having on a train. Matched as prefixes
 * against the query key's first element, which for every generated hook is the
 * request path (`/api/v1/g/3/tasks/12`) — see `src/api/generated/*`.
 *
 * `{g}` stands in for the `/g/{guildId}` segment so one entry covers every
 * guild without the prefix list having to know any guild ids.
 */
const PERSIST_ALLOWLIST = [
  // Guild content — the things somebody actually opened.
  "/api/v1/g/{g}/initiatives",
  "/api/v1/g/{g}/projects",
  "/api/v1/g/{g}/tasks",
  "/api/v1/g/{g}/subtasks",
  "/api/v1/g/{g}/task-statuses",
  "/api/v1/g/{g}/documents",
  "/api/v1/g/{g}/queues",
  "/api/v1/g/{g}/queue-items",
  "/api/v1/g/{g}/counters",
  "/api/v1/g/{g}/counter-groups",
  "/api/v1/g/{g}/calendars",
  "/api/v1/g/{g}/calendar-events",
  "/api/v1/g/{g}/calendar-entries",
  "/api/v1/g/{g}/dashboards",
  "/api/v1/g/{g}/posts",
  "/api/v1/g/{g}/comments",
  "/api/v1/g/{g}/tags",
  "/api/v1/g/{g}/property-definitions",
  "/api/v1/g/{g}/fields",
  "/api/v1/g/{g}/tools",
  // Cross-guild "my" reads that the home screens are built from.
  "/api/v1/me/tasks",
  "/api/v1/me/projects",
  "/api/v1/me/tools",
  // Enough identity and structure to render the shell around all of it.
  "/api/v1/users/me",
  "/api/v1/guilds",
  "/api/v1/recents",
] as const;

/**
 * Paths that are never written, whatever the allowlist above says. Settings and
 * administration are configuration rather than content; search and trash are
 * derived surfaces; none of them is "what I was reading".
 */
const PERSIST_DENYLIST = [
  "/api/v1/auth/",
  "/api/v1/config",
  "/api/v1/settings",
  "/api/v1/admin",
  "/api/v1/access-grants",
  "/api/v1/ai-settings",
  "/api/v1/webhooks",
  "/api/v1/exports",
  "/api/v1/imports",
  "/api/v1/storage",
  "/api/v1/native",
  "/api/v1/search",
  "/api/v1/trash",
  // Messages keep their own store, with its own rules about what stays on a
  // device (see `src/crypto/`). They are not duplicated here.
  "/api/v1/me/dm-settings",
  "/api/v1/me/connections",
  "/api/v1/me/message-requests",
  "/dm/",
  "/dm-permission",
] as const;

const GUILD_SEGMENT = /^\/api\/v1\/g\/(\d+)(?=\/|$)/;

/**
 * Guilds the user reaches only through a live, time-bound grant rather than
 * membership. Their content is not written to disk, since the grant can end
 * while the device is away. `useGuilds` marks these `accessType: "grant"` and
 * keeps this set current; the dehydrate filter reads it.
 */
let grantOnlyGuildIds: ReadonlySet<number> = new Set();

/**
 * Replace the set. Only for a reading that actually came back — a narrower set
 * than the truth would let a grant guild's content through.
 */
export const setGrantOnlyGuildIds = (ids: Iterable<number>): void => {
  grantOnlyGuildIds = new Set(ids);
};

/**
 * Widen the set without narrowing it, for when the grant list could not be
 * read. The cost of keeping a guild in here that has since become an ordinary
 * membership is only that its content is not cached until the next good read.
 */
export const addGrantOnlyGuildIds = (ids: Iterable<number>): void => {
  grantOnlyGuildIds = new Set([...grantOnlyGuildIds, ...ids]);
};

/** Test seam. */
export const resetGrantOnlyGuildIds = (): void => {
  grantOnlyGuildIds = new Set();
};

/** The guild a request path addresses, or null for a platform-level path. */
export const guildIdOfPath = (path: string): number | null => {
  const match = GUILD_SEGMENT.exec(path);
  return match ? Number(match[1]) : null;
};

const matchesAllowlist = (path: string): boolean =>
  PERSIST_ALLOWLIST.some((entry) => {
    const prefix = entry.replace("/g/{g}", `/g/${guildIdOfPath(path) ?? ""}`);
    return path === prefix || path.startsWith(`${prefix}/`) || path.startsWith(`${prefix}?`);
  });

const matchesDenylist = (path: string): boolean =>
  PERSIST_DENYLIST.some((entry) => path.includes(entry));

/**
 * Whether one request path may be written to disk. Default deny: a path has to
 * be named by the allowlist, must not be named by the denylist, and must not
 * belong to a guild reached only by a grant.
 */
export const isPersistablePath = (path: string): boolean => {
  if (!path.startsWith("/api/v1/")) return false;
  if (matchesDenylist(path)) return false;
  if (!matchesAllowlist(path)) return false;

  const guildId = guildIdOfPath(path);
  if (guildId !== null && grantOnlyGuildIds.has(guildId)) return false;

  return true;
};

/**
 * The dehydrate filter. Only successful reads of allowlisted paths are kept —
 * a cached error is noise, and every hand-written query key (`["dm", …]`,
 * `["contacts", …]`) falls out here because its first element is not a path.
 */
export const shouldPersistQuery = (query: Query): boolean => {
  if (query.state.status !== "success") return false;
  const [first] = query.queryKey;
  if (typeof first !== "string") return false;
  return isPersistablePath(first);
};

/**
 * Native only, for now. Extending this to installed PWAs is a separate decision
 * — see `history/offline-reading-design.md`.
 */
export const isOfflineCacheEnabled = (): boolean => Capacitor.isNativePlatform();

const store = createIdbStore(IDB_NAME, IDB_STORE);

/**
 * Ties the cache to one server: `persistQueryClient` discards any blob whose
 * buster differs, so pointing the app at another deployment starts empty.
 *
 * The user half cannot be done here, since nobody is confirmed at boot — that
 * is `restoredIdentityMismatch` below.
 */
export const offlineCacheBuster = (serverUrl: string): string =>
  `v${OFFLINE_CACHE_SCHEMA_VERSION}|${serverUrl}`;

/** Whose cache was restored at boot, per the session snapshot beside it. */
let restoredForUserId: number | null = null;

export const noteRestoredIdentity = (userId: number | null): void => {
  restoredForUserId = userId;
};

/**
 * True when the server confirms a different user than the one whose cache was
 * restored, which can happen when a sign-out did not complete. The caller
 * clears the query client and purges the blob.
 */
export const restoredIdentityMismatch = (confirmedUserId: number): boolean => {
  const mismatch = restoredForUserId !== null && restoredForUserId !== confirmedUserId;
  restoredForUserId = confirmedUserId;
  return mismatch;
};

/**
 * Whether anything may be written to disk right now: false until the server has
 * confirmed who is here, so only content it has just served is recorded.
 *
 * This is also what keeps the max age meaningful. Every save restamps the
 * blob's timestamp, and a launch with no signal re-dehydrates the cache it just
 * restored — so without this, a device opened offline each morning would renew
 * its own expiry indefinitely.
 */
let writesAllowed = false;

export const setOfflineWritesAllowed = (allowed: boolean): void => {
  writesAllowed = allowed;
};

export const createOfflineCachePersister = () => {
  const persister = createAsyncStoragePersister({
    storage: store,
    key: IDB_KEY,
    // The blob is small — the allowlist keeps it to what somebody actually
    // opened — but a phone should not re-serialize it on every keystroke.
    throttleTime: 2000,
    // A cache we can't write is a cache we don't keep: dropping it is always
    // safe, since nothing is ever read from it while the device has signal.
    retry: () => undefined,
  });

  return {
    ...persister,
    persistClient: (client: Parameters<typeof persister.persistClient>[0]) => {
      if (!writesAllowed) return undefined;
      setItem(SYNCED_AT_KEY, String(client.timestamp));
      return persister.persistClient(client);
    },
  };
};

/** Epoch ms of the last write, or null if this device has never cached. */
export const offlineCacheSyncedAt = (): number | null => {
  const raw = getItem(SYNCED_AT_KEY);
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
};

/**
 * The `persistOptions` half. Kept beside the filter so the two cannot drift:
 * a persisted blob is only ever restored when it is inside the window *and*
 * belongs to this user on this server, and only ever written for a query the
 * filter approved. Mutations are never persisted — that is the line that keeps
 * offline reading from quietly becoming offline writing.
 */
export const offlinePersistOptions = (buster: string) => ({
  persister: createOfflineCachePersister(),
  maxAge: OFFLINE_CACHE_MAX_AGE_MS,
  buster,
  dehydrateOptions: {
    shouldDehydrateQuery: shouldPersistQuery,
    shouldDehydrateMutation: () => false,
  },
});

/** Erase the persisted cache. Called on sign-out and on a rejected session. */
export const purgeOfflineCache = async (): Promise<void> => {
  removeItem(SYNCED_AT_KEY);
  try {
    await store.removeItem(IDB_KEY);
  } catch {
    // Best effort: a cache we cannot delete is one we also could not read, and
    // the buster means the next session will not accept it either way.
  }
};
