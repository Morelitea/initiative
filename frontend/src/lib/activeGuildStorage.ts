/**
 * This tab's community, remembered as the default for the next fresh tab.
 *
 * The community a request operates in comes from the URL, never from here —
 * this is only what a tab opened with no community in its path should fall back
 * to. It lives apart from `useGuilds` so code that runs before React does (the
 * offline cache deciding which community's content to restore first) can read
 * it without pulling a provider in.
 */

import { getItem, removeItem, setItem } from "@/lib/storage";

const GUILD_STORAGE_KEY = "initiative-active-guild";

export const readStoredGuildId = (): number | null => {
  const stored = getItem(GUILD_STORAGE_KEY);
  if (!stored) {
    return null;
  }
  const parsed = Number(stored);
  return Number.isFinite(parsed) ? parsed : null;
};

export const persistGuildId = (guildId: number | null): void => {
  if (guildId === null) {
    removeItem(GUILD_STORAGE_KEY);
  } else {
    setItem(GUILD_STORAGE_KEY, String(guildId));
  }
};
