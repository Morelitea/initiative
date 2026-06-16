import type { AxiosError } from "axios";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { apiClient } from "@/api/client";
import type { AccessGrantRead, GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { resetGuildScopedQueries } from "@/api/query-keys";
import { useAuth } from "@/hooks/useAuth";
import { toast } from "@/lib/chesterToast";
import { getItem, removeItem, setItem } from "@/lib/storage";

/**
 * A guild entry in the switcher. Member guilds come from `/guilds/`; entries
 * the user can only reach via a live, time-bound PAM access grant are
 * synthesized from `/access-grants/` and flagged with `accessType: "grant"`
 * so the UI can mark them temporary and enforce read-only.
 */
export type GuildEntry = GuildRead & {
  accessType?: "member" | "grant";
  grantExpiresAt?: string | null;
  grantAccessLevel?: "read" | "read_write" | null;
};

interface GuildContextValue {
  guilds: GuildEntry[];
  /** This tab's guild, taken from its `/g/{guildId}` URL (the route layout
   * calls syncGuildFromUrl). Per-tab — no server-held context — so two tabs can
   * sit in two different guilds at once. */
  activeGuildId: number | null;
  activeGuild: GuildEntry | null;
  /** True when the active guild is reached via a read-only grant — writes are
   * blocked server-side, so the UI should hide write affordances. */
  activeGuildReadOnly: boolean;
  loading: boolean;
  error: string | null;
  refreshGuilds: () => Promise<void>;
  switchGuild: (guildId: number) => Promise<void>;
  syncGuildFromUrl: (guildId: number) => Promise<void>;
  createGuild: (input: { name: string; description?: string }) => Promise<GuildRead>;
  updateGuildInState: (guild: GuildRead) => void;
  reorderGuilds: (guildIds: number[]) => void;
  canCreateGuilds: boolean;
}

export const GuildContext = createContext<GuildContextValue | undefined>(undefined);

const GUILD_STORAGE_KEY = "initiative-active-guild";

const readStoredGuildId = (): number | null => {
  const stored = getItem(GUILD_STORAGE_KEY);
  if (!stored) {
    return null;
  }
  const parsed = Number(stored);
  return Number.isFinite(parsed) ? parsed : null;
};

const persistGuildId = (guildId: number | null) => {
  if (guildId === null) {
    removeItem(GUILD_STORAGE_KEY);
  } else {
    setItem(GUILD_STORAGE_KEY, String(guildId));
  }
};

const sortGuilds = (guildList: GuildEntry[]): GuildEntry[] => {
  return [...guildList].sort((a, b) => {
    // Grant (temporary) guilds always sort after member guilds.
    const aGrant = a.accessType === "grant" ? 1 : 0;
    const bGrant = b.accessType === "grant" ? 1 : 0;
    if (aGrant !== bGrant) {
      return aGrant - bGrant;
    }
    const positionDelta = (a.position ?? 0) - (b.position ?? 0);
    if (positionDelta !== 0) {
      return positionDelta;
    }
    return a.id - b.id;
  });
};

/** Build a synthetic switcher entry for a guild reachable only via a live grant. */
const grantEntry = (grant: AccessGrantRead): GuildEntry => ({
  id: grant.guild_id,
  name: grant.guild_name ?? `Guild #${grant.guild_id}`,
  description: null,
  icon_base64: null,
  role: "member",
  position: Number.MAX_SAFE_INTEGER,
  retention_days: null,
  member_count: 0,
  created_at: grant.requested_at,
  updated_at: grant.requested_at,
  accessType: "grant",
  grantExpiresAt: grant.expires_at,
  grantAccessLevel: grant.access_level,
});

export const GuildProvider = ({ children }: { children: ReactNode }) => {
  const { user, refreshUser } = useAuth();
  const [guilds, setGuilds] = useState<GuildEntry[]>([]);
  const [activeGuildId, setActiveGuildId] = useState<number | null>(readStoredGuildId);
  // Start as true - we're loading until first fetch completes (or until we know we shouldn't fetch)
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reorderDebounceRef = useRef<number | null>(null);
  const pendingOrderRef = useRef<number[] | null>(null);
  const hasFetchedRef = useRef(false);
  const activeGuildIdRef = useRef(activeGuildId);
  activeGuildIdRef.current = activeGuildId;

  const canCreateGuilds = user?.can_create_guilds ?? true;

  // Persist this tab's guild as the fresh-tab default (read once at mount).
  useEffect(() => {
    persistGuildId(activeGuildId);
  }, [activeGuildId]);

  const applyGuildState = useCallback((guildList: GuildEntry[]) => {
    const sortedGuilds = sortGuilds(guildList);
    setGuilds(sortedGuilds);

    // Use functional update to avoid overriding in-flight guild switches.
    // Only change activeGuildId when the current value is no longer valid.
    setActiveGuildId((prev) => {
      if (prev !== null && sortedGuilds.some((guild) => guild.id === prev)) {
        return prev;
      }

      // Fall back to stored guild (client session preference)
      const stored = readStoredGuildId();
      if (stored && sortedGuilds.some((guild) => guild.id === stored)) {
        return stored;
      }

      // Last resort: first available guild
      return sortedGuilds[0]?.id ?? null;
    });
  }, []);

  const refreshGuilds = useCallback(async () => {
    if (!user) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      setLoading(false);
      return;
    }

    // Only show loading indicator on initial load, not background refreshes
    if (!hasFetchedRef.current) setLoading(true);

    setError(null);
    try {
      const response = await apiClient.get<GuildRead[]>("/guilds/");
      hasFetchedRef.current = true;

      // Also surface guilds the user can only reach via a live PAM grant, so
      // they appear in the switcher (flagged temporary) and can actually be
      // entered. Best-effort: a failure here must not break the guild list.
      const memberIds = new Set(response.data.map((g) => g.id));
      let grantGuilds: GuildEntry[] = [];
      try {
        const grants = await apiClient.get<AccessGrantRead[]>("/access-grants/", {
          params: { mine: true },
        });
        const liveByGuild = new Map<number, AccessGrantRead>();
        for (const grant of grants.data) {
          if (grant.is_live && !memberIds.has(grant.guild_id)) {
            // Keep the latest-expiring live grant per guild.
            const existing = liveByGuild.get(grant.guild_id);
            if (!existing || (grant.expires_at ?? "") > (existing.expires_at ?? "")) {
              liveByGuild.set(grant.guild_id, grant);
            }
          }
        }
        grantGuilds = Array.from(liveByGuild.values()).map(grantEntry);
      } catch (grantErr) {
        console.error("Failed to load access grants for guild switcher", grantErr);
      }

      applyGuildState([...response.data, ...grantGuilds]);
    } catch (err) {
      console.error("Failed to load guilds", err);
      const axiosError = err as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      setError(detail ?? "Unable to load guilds.");
    } finally {
      setLoading(false);
    }
  }, [user, applyGuildState]);

  const flushPendingOrder = useCallback(async () => {
    if (!pendingOrderRef.current) {
      return;
    }
    const payload = pendingOrderRef.current;
    pendingOrderRef.current = null;
    try {
      await apiClient.put("/guilds/order", { guildIds: payload });
    } catch (err) {
      console.error("Failed to save guild order", err);
      toast.error("Unable to save guild order. Refreshing…");
      await refreshGuilds();
    }
  }, [refreshGuilds]);

  const scheduleOrderSave = useCallback(
    (guildIds: number[]) => {
      if (guildIds.length === 0) {
        return;
      }
      pendingOrderRef.current = guildIds;
      if (typeof window === "undefined") {
        void flushPendingOrder();
        return;
      }
      if (reorderDebounceRef.current) {
        window.clearTimeout(reorderDebounceRef.current);
      }
      reorderDebounceRef.current = window.setTimeout(() => {
        reorderDebounceRef.current = null;
        void flushPendingOrder();
      }, 500);
    },
    [flushPendingOrder]
  );

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && reorderDebounceRef.current) {
        window.clearTimeout(reorderDebounceRef.current);
      }
      if (pendingOrderRef.current) {
        void flushPendingOrder();
      }
    };
  }, [flushPendingOrder]);

  useEffect(() => {
    if (!user) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      setLoading(false);
      hasFetchedRef.current = false;
      return;
    }
    void refreshGuilds();
  }, [user, refreshGuilds]);

  const switchGuild = useCallback(
    async (guildId: number) => {
      // The guild lives in the URL: callers navigate to /g/{guildId} and the
      // route layout calls syncGuildFromUrl. Here we just move this tab's local
      // state and drop the previous guild's now-wrong cached query data. No
      // server context — per-tab only, so two tabs can hold different guilds.
      if (!user || guildId === activeGuildIdRef.current) {
        return;
      }
      setActiveGuildId(guildId);
      await resetGuildScopedQueries();
      await Promise.all([refreshGuilds(), refreshUser()]);
    },
    [user, refreshGuilds, refreshUser]
  );

  /**
   * Adopt the guild from a /g/{guildId} route into this tab's local state
   * (rail highlight, redirect targets, query keys). Per-tab only — no server
   * context — so each tab tracks the guild in its own URL.
   */
  const syncGuildFromUrl = useCallback(async (guildId: number) => {
    if (guildId === activeGuildIdRef.current) {
      return;
    }
    setActiveGuildId(guildId);
    persistGuildId(guildId);
    await resetGuildScopedQueries();
  }, []);

  // Each browser tab holds its OWN guild, taken from its `/g/{guildId}` URL —
  // tabs do NOT converge. We deliberately do not listen for the guild storage
  // event, so a guild switch in one tab never drags another tab's context with
  // it; that is what lets two tabs sit in two different guilds at once. (The
  // persisted id is only a fresh-tab default, read once at mount.)

  const reorderGuilds = useCallback(
    (guildIds: number[]) => {
      if (guildIds.length === 0) {
        return;
      }
      if (guilds.length <= 1) {
        return;
      }
      const uniqueIds: number[] = [];
      const seenIds = new Set<number>();
      for (const id of guildIds) {
        if (seenIds.has(id)) {
          continue;
        }
        seenIds.add(id);
        uniqueIds.push(id);
      }
      setGuilds((prev) => {
        if (prev.length <= 1) {
          return prev;
        }
        const lookup = new Map(prev.map((guild) => [guild.id, guild]));
        const ordered: GuildRead[] = [];
        uniqueIds.forEach((id) => {
          const match = lookup.get(id);
          if (match) {
            ordered.push({ ...match });
            lookup.delete(id);
          }
        });
        ordered.push(...Array.from(lookup.values()).map((guild) => ({ ...guild })));
        const withPositions = ordered.map((guild, index) => ({
          ...guild,
          position: index,
        }));
        return sortGuilds(withPositions);
      });
      scheduleOrderSave(uniqueIds);
    },
    [guilds.length, scheduleOrderSave]
  );

  const createGuild = useCallback(
    async ({ name, description }: { name: string; description?: string }) => {
      if (!user) {
        throw new Error("You must be signed in to create a guild.");
      }
      if (!canCreateGuilds) {
        throw new Error("Guild creation is disabled.");
      }

      const trimmedName = name.trim();
      if (!trimmedName) {
        throw new Error("Guild name is required.");
      }

      const response = await apiClient.post<GuildRead>("/guilds/", {
        name: trimmedName,
        description: description?.trim() || undefined,
      });

      await Promise.all([refreshGuilds(), refreshUser()]);

      return response.data;
    },
    [user, canCreateGuilds, refreshGuilds, refreshUser]
  );

  const updateGuildInState = useCallback((guild: GuildRead) => {
    setGuilds((prev) => {
      let replaced = false;
      const next = prev.map((existing) => {
        if (existing.id === guild.id) {
          replaced = true;
          return guild;
        }
        return existing;
      });
      const merged = replaced ? next : next.concat(guild);
      return sortGuilds(merged);
    });
  }, []);

  const activeGuild = useMemo(
    () => guilds.find((guild) => guild.id === activeGuildId) ?? null,
    [guilds, activeGuildId]
  );

  // Read-only when the active guild is a grant that isn't read-write.
  const activeGuildReadOnly =
    activeGuild?.accessType === "grant" && activeGuild?.grantAccessLevel !== "read_write";

  const value: GuildContextValue = {
    guilds,
    activeGuildId,
    activeGuild,
    activeGuildReadOnly,
    loading,
    error,
    refreshGuilds,
    switchGuild,
    syncGuildFromUrl,
    createGuild,
    updateGuildInState,
    reorderGuilds,
    canCreateGuilds,
  };

  return <GuildContext.Provider value={value}>{children}</GuildContext.Provider>;
};

export const useGuilds = () => {
  const context = useContext(GuildContext);
  if (!context) {
    throw new Error("useGuilds must be used within a GuildProvider");
  }
  return context;
};
