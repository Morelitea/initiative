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

import { apiClient, setCurrentGuildId } from "@/api/client";
import type { AccessGrantRead, GuildRead } from "@/api/generated/initiativeAPI.schemas";
import { setGuildContextApiV1UsersMeGuildContextPut } from "@/api/generated/users/users";
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
  activeGuildId: number | null;
  /** The guild the SERVER currently holds for this user (users.active_guild_id
   * mirror); null = personal mode. Unlike activeGuildId (the local "last
   * guild" preference), this is what actually scopes requests — long-lived
   * consumers like the events websocket must key off it. */
  serverGuildId: number | null;
  activeGuild: GuildEntry | null;
  /** True when the active guild is reached via a read-only grant — writes are
   * blocked server-side, so the UI should hide write affordances. */
  activeGuildReadOnly: boolean;
  loading: boolean;
  error: string | null;
  refreshGuilds: () => Promise<void>;
  switchGuild: (guildId: number) => Promise<void>;
  syncGuildFromUrl: (guildId: number) => Promise<void>;
  /** Enter personal (cross-guild) mode server-side. Called when the user
   * lands on the personal home page. */
  syncPersonalContext: () => Promise<void>;
  /** Adopt a guild switch made in another tab (no server PUT — the other tab
   * already moved the server-held context). */
  adoptExternalGuildSwitch: (guildId: number | null) => Promise<void>;
  createGuild: (input: { name: string; description?: string }) => Promise<GuildRead>;
  updateGuildInState: (guild: GuildRead) => void;
  reorderGuilds: (guildIds: number[]) => void;
  canCreateGuilds: boolean;
}

export const GuildContext = createContext<GuildContextValue | undefined>(undefined);

const GUILD_STORAGE_KEY = "initiative-active-guild";

/** Fired after this tab adopts a guild switch made in another tab, so a
 * router-aware component can move off a now-wrong guild URL. */
export const GUILD_CONTEXT_CONVERGED_EVENT = "initiative:guild-context-converged";

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

  // Sync API Client whenever ID changes
  useEffect(() => {
    setCurrentGuildId(activeGuildId);
    persistGuildId(activeGuildId);
  }, [activeGuildId]);

  // The guild context the server currently holds for this user
  // (users.active_guild_id; null = personal mode). Seeded from the loaded
  // user so a fresh tab doesn't re-PUT a context the server already has.
  // The ref is the synchronous source of truth for the idempotence check;
  // the state mirror lets reactive consumers (events websocket) follow it.
  const serverContextRef = useRef<number | null | undefined>(undefined);
  const [serverGuildId, setServerGuildId] = useState<number | null>(null);
  useEffect(() => {
    if (user && serverContextRef.current === undefined) {
      serverContextRef.current = user.active_guild_id ?? null;
      setServerGuildId(user.active_guild_id ?? null);
    }
    if (!user) {
      serverContextRef.current = undefined;
      setServerGuildId(null);
    }
  }, [user]);

  /** Push the server-held guild context (idempotent). All guild-scoped
   * requests resolve their guild from this flag, so it must land before the
   * new context's fetches fire. Returns true when the server context actually
   * changed (a PUT was sent). Throws if the PUT fails. */
  const pushServerContext = useCallback(async (guildId: number | null) => {
    if (serverContextRef.current === guildId) {
      return false;
    }
    await setGuildContextApiV1UsersMeGuildContextPut({ guild_id: guildId });
    serverContextRef.current = guildId;
    setServerGuildId(guildId);
    return true;
  }, []);

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
      // Don't switch if we are already there
      if (!user || guildId === activeGuildIdRef.current) {
        // Still make sure the server context matches (e.g. coming back from
        // personal mode to the already-highlighted guild) — and if it moved,
        // refetch the guild-scoped queries that errored without it.
        try {
          if (await pushServerContext(guildId)) {
            await resetGuildScopedQueries();
          }
        } catch (err) {
          console.error("Failed to set guild context", err);
        }
        return;
      }

      // The server-held context must land BEFORE the new guild's fetches —
      // every guild-scoped request resolves its guild from it.
      try {
        await pushServerContext(guildId);
      } catch (err) {
        console.error("Failed to set guild context", err);
        toast.error("Unable to switch guild. Please try again.");
        return;
      }

      // Update local state so UI reacts
      setActiveGuildId(guildId);

      // Clear guild-scoped query cache so stale data from the previous guild isn't shown
      await resetGuildScopedQueries();

      // Refresh data in background to ensure everything is synced
      await Promise.all([refreshGuilds(), refreshUser()]);
    },
    [user, pushServerContext, refreshGuilds, refreshUser]
  );

  /**
   * Sync guild context from URL without full navigation.
   * Used by guild-scoped routes to sync context from URL params (deep links,
   * opened tabs, cross-guild navigation).
   */
  const syncGuildFromUrl = useCallback(
    async (guildId: number) => {
      // Always converge the server-held context first — the local id can
      // already match while the server flag points elsewhere (fresh tab,
      // return from personal mode). pushServerContext is idempotent.
      let contextChanged = false;
      try {
        contextChanged = await pushServerContext(guildId);
      } catch (err) {
        // Abort: flipping the local UI into a guild the server context never
        // reached would have every guild-scoped request resolving under the
        // OLD context — wrong guild, no error indication. Leave local state
        // alone so UI and server stay consistent; the user can retry.
        console.error("Failed to set guild context", err);
        toast.error("Unable to enter guild. Please try again.");
        return;
      }

      if (guildId === activeGuildIdRef.current) {
        // The local guild didn't change but the SERVER context did (e.g.
        // returning to the guild from personal mode, where guild-scoped
        // queries 409ed): those cached errors/empties won't refetch on their
        // own — sidebar counts would stay zeroed — so reset them now that
        // requests resolve in this guild again.
        if (contextChanged) {
          await resetGuildScopedQueries();
        }
        return;
      }

      // Update local state immediately
      setActiveGuildId(guildId);
      setCurrentGuildId(guildId);
      persistGuildId(guildId);

      // Clear guild-scoped query cache so stale data from the previous guild isn't shown
      await resetGuildScopedQueries();
    },
    [pushServerContext]
  );

  /**
   * Enter personal (cross-guild) mode server-side. The local activeGuildId is
   * kept as the user's "last guild" for rail highlight and redirect targets —
   * only the server-held flag goes null.
   */
  const syncPersonalContext = useCallback(async () => {
    try {
      await pushServerContext(null);
    } catch (err) {
      console.error("Failed to enter personal mode", err);
    }
  }, [pushServerContext]);

  /**
   * Another tab switched guilds (storage event): the server-held context has
   * already moved, so converge this tab without re-PUTting — update local
   * state and drop guild-scoped caches so nothing stale repaints.
   */
  const adoptExternalGuildSwitch = useCallback(async (guildId: number | null) => {
    serverContextRef.current = guildId;
    setServerGuildId(guildId);
    if (guildId === null || guildId === activeGuildIdRef.current) {
      return;
    }
    setActiveGuildId(guildId);
    await resetGuildScopedQueries();
    // Let a router-aware listener (AppLayout) move this tab off a guild URL
    // that no longer matches the converged context.
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(GUILD_CONTEXT_CONVERGED_EVENT, { detail: { guildId } }));
    }
  }, []);

  // Tabs converge: the user is in exactly one context at a time, everywhere.
  // When another tab switches guilds it persists the id (storage event fires
  // only in OTHER tabs) — adopt the switch here so this tab can't keep
  // operating against a server context that has moved.
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key !== GUILD_STORAGE_KEY) {
        return;
      }
      const parsed = event.newValue === null ? null : Number(event.newValue);
      void adoptExternalGuildSwitch(Number.isFinite(parsed as number) ? parsed : null);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [adoptExternalGuildSwitch]);

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
    serverGuildId,
    activeGuild,
    activeGuildReadOnly,
    loading,
    error,
    refreshGuilds,
    switchGuild,
    syncGuildFromUrl,
    syncPersonalContext,
    adoptExternalGuildSwitch,
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
