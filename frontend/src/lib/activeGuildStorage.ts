/**
 * Which community each account on this browser last had open.
 *
 * The community a request operates in comes from the URL, never from here —
 * this is only what a tab opened with no community in its path should fall back
 * to. It lives apart from `useGuilds` so code that runs before React does (the
 * offline cache deciding which community's content to restore first) can read
 * it without pulling a provider in.
 *
 * Kept per account, because a browser is shared and an account's last community
 * is not the next account's. Code running before anyone is signed in has no
 * account to ask about, so it reads whoever was here last — right whenever it is
 * the same person reopening the app, and corrected by the guild list when it
 * isn't.
 */

import { getItem, removeItem, setItem } from "@/lib/storage";

const GUILD_STORAGE_KEY = "initiative-active-guild";

type Remembered = {
  /** The account this browser saw most recently, if any. */
  last: number | null;
  /** Account id (as a string key) to the community it last had open. */
  byUser: Record<string, number>;
};

const EMPTY: Remembered = { last: null, byUser: {} };

const read = (): Remembered => {
  const stored = getItem(GUILD_STORAGE_KEY);
  if (!stored) return EMPTY;
  // A bare number is what this key held before it was kept per account.
  // ``legacyGuildId`` serves it to the readers; there is nothing per-account in
  // it, and the first write under the new shape replaces it.
  if (Number.isFinite(Number(stored))) return EMPTY;
  try {
    const parsed = JSON.parse(stored) as Partial<Remembered> | null;
    if (!parsed || typeof parsed !== "object") return EMPTY;
    return {
      last: typeof parsed.last === "number" ? parsed.last : null,
      byUser: parsed.byUser && typeof parsed.byUser === "object" ? parsed.byUser : {},
    };
  } catch {
    return EMPTY;
  }
};

const legacyGuildId = (): number | null => {
  const stored = getItem(GUILD_STORAGE_KEY);
  if (!stored) return null;
  const parsed = Number(stored);
  return Number.isFinite(parsed) ? parsed : null;
};

/**
 * The community to open before anyone has said who they are — whoever used this
 * browser last. A fallback, never an authority: the guild list replaces it as
 * soon as it answers.
 */
export const readStoredGuildId = (): number | null => {
  const legacy = legacyGuildId();
  if (legacy !== null) return legacy;
  const { last, byUser } = read();
  if (last === null) return null;
  return byUser[String(last)] ?? null;
};

/** The community this account last had open on this browser. */
export const readStoredGuildIdFor = (userId: number | null): number | null => {
  if (userId === null) return null;
  const legacy = legacyGuildId();
  if (legacy !== null) return legacy;
  return read().byUser[String(userId)] ?? null;
};

/** Remember `guildId` as this account's, and this account as the latest. */
export const persistGuildId = (guildId: number | null, userId: number | null): void => {
  if (userId === null) return;
  const { byUser } = read();
  const next: Remembered = { last: userId, byUser: { ...byUser } };
  if (guildId === null) {
    delete next.byUser[String(userId)];
  } else {
    next.byUser[String(userId)] = guildId;
  }
  if (next.last === null && Object.keys(next.byUser).length === 0) {
    removeItem(GUILD_STORAGE_KEY);
    return;
  }
  setItem(GUILD_STORAGE_KEY, JSON.stringify(next));
};
