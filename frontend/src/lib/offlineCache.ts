/**
 * What a phone with no signal is allowed to still show.
 *
 * The whole argument for this file is in `history/offline-reading-design.md`;
 * the short version is that a cache on a disconnected device is an
 * authorization decision that can never be re-derived, so it is treated not as
 * permission to read but as a redisplay of bytes this device already lawfully
 * received — shown only when asking is impossible, expiring on the clock, and
 * destroyed with the identity that received them.
 *
 * Four rules, and they are the security argument:
 *
 *   1. Online, the cache decides nothing — every query still asks, and the
 *      server's answer (including a refusal) wins. `staleTime` stays 0, so
 *      restored data refetches the moment there is signal.
 *   2. It expires on a fixed clock, because offline there are no events.
 *   3. It is bound to one user on one server and dies with that pairing.
 *   4. It holds only what a redisplay needs: default deny, an allowlist of
 *      read-only content paths, and a denylist over the top of that.
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
 * Paths that must never reach disk even if an allowlist entry above someday
 * grows to cover them. Configuration is not content, some of it is
 * secret-adjacent, and search and trash are surfaces about things the user may
 * since have lost — none of them is "what I was reading".
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
  // Message plaintext is decrypted under a key store with its own
  // erase-on-sign-out contract; a durable copy beside it defeats that.
  "/api/v1/me/dm-settings",
  "/api/v1/me/connections",
  "/api/v1/me/message-requests",
  "/dm/",
  "/dm-permission",
] as const;

const GUILD_SEGMENT = /^\/api\/v1\/g\/(\d+)(?=\/|$)/;

/**
 * Guilds the user reaches only through a live PAM or break-glass grant.
 *
 * These grants are time-bound and audited precisely so the access does not
 * outlive its window, so their content must not be written to disk at all.
 * `useGuilds` knows which guilds these are (it marks them `accessType: "grant"`)
 * and keeps this set current; the dehydrate filter reads it.
 */
let grantOnlyGuildIds: ReadonlySet<number> = new Set();

export const setGrantOnlyGuildIds = (ids: Iterable<number>): void => {
  grantOnlyGuildIds = new Set(ids);
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
 * Native only, for now.
 *
 * An app sandbox is an OS-level boundary; browser storage is readable by anyone
 * with the unlocked profile, and today closing a tab leaves no readable content
 * behind. Extending this to installed PWAs deserves its own argument rather
 * than arriving as a side effect of a task titled "[Mobile]".
 */
export const isOfflineCacheEnabled = (): boolean => Capacitor.isNativePlatform();

const store = createIdbStore(IDB_NAME, IDB_STORE);

/**
 * The cache is bound to one server: `persistQueryClient` throws away any blob
 * whose buster differs, so pointing the app at another deployment discards the
 * previous one's content rather than trying to read it.
 *
 * Binding it to a *user* cannot be done here — at boot nobody has been
 * confirmed yet — so that half is `restoredIdentityMismatch` below.
 */
export const offlineCacheBuster = (serverUrl: string): string =>
  `v${OFFLINE_CACHE_SCHEMA_VERSION}|${serverUrl}`;

/** Whose cache was restored at boot, per the session snapshot beside it. */
let restoredForUserId: number | null = null;

export const noteRestoredIdentity = (userId: number | null): void => {
  restoredForUserId = userId;
};

/**
 * True when the server has now confirmed somebody other than the user whose
 * cache we restored — the case where sign-out never ran (app killed, token
 * revoked server-side) and the next person would otherwise be handed the last
 * one's content. The caller clears the query client and purges the blob.
 */
export const restoredIdentityMismatch = (confirmedUserId: number): boolean => {
  const mismatch = restoredForUserId !== null && restoredForUserId !== confirmedUserId;
  restoredForUserId = confirmedUserId;
  return mismatch;
};

/**
 * Whether anything may be written to disk right now.
 *
 * False until the server has confirmed who is here, which does two jobs. It
 * keeps a session running on an unconfirmed snapshot from writing anything at
 * all — we only ever record content the server just agreed to hand over. And it
 * stops the max age from being a lie: every save restamps the blob's timestamp,
 * so a device opened offline each morning would otherwise renew its own cache
 * forever and never age out.
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
