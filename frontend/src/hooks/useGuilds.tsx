import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { AxiosError } from "axios";
import { toast } from "sonner";

import { apiClient, setCurrentGuildId } from "@/api/client";
import type { Guild } from "@/types/api";
import { useAuth } from "@/hooks/useAuth";

interface GuildContextValue {
  guilds: Guild[];
  activeGuildId: number | null;
  activeGuild: Guild | null;
  loading: boolean;
  error: string | null;
  refreshGuilds: () => Promise<void>;
  switchGuild: (guildId: number) => Promise<void>;
  syncGuildFromUrl: (guildId: number) => Promise<void>;
  createGuild: (input: { name: string; description?: string }) => Promise<Guild>;
  updateGuildInState: (guild: Guild) => void;
  reorderGuilds: (guildIds: number[]) => void;
  canCreateGuilds: boolean;
}

const GuildContext = createContext<GuildContextValue | undefined>(undefined);

const GUILD_STORAGE_KEY = "initiative-active-guild";

const readStoredGuildId = (): number | null => {
  if (typeof window === "undefined") {
    return null;
  }
  const stored = window.localStorage.getItem(GUILD_STORAGE_KEY);
  if (!stored) {
    return null;
  }
  const parsed = Number(stored);
  return Number.isFinite(parsed) ? parsed : null;
};

const persistGuildId = (guildId: number | null) => {
  if (typeof window === "undefined") {
    return;
  }
  if (guildId === null) {
    window.localStorage.removeItem(GUILD_STORAGE_KEY);
  } else {
    window.localStorage.setItem(GUILD_STORAGE_KEY, String(guildId));
  }
};

const sortGuilds = (guildList: Guild[]): Guild[] => {
  return [...guildList].sort((a, b) => {
    const positionDelta = (a.position ?? 0) - (b.position ?? 0);
    if (positionDelta !== 0) {
      return positionDelta;
    }
    return a.id - b.id;
  });
};

export const GuildProvider = ({ children }: { children: ReactNode }) => {
  const { user, token, refreshUser } = useAuth();
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [activeGuildId, setActiveGuildId] = useState<number | null>(readStoredGuildId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reorderDebounceRef = useRef<number | null>(null);
  const pendingOrderRef = useRef<number[] | null>(null);

  const canCreateGuilds = user?.can_create_guilds ?? true;

  // Sync API Client whenever ID changes
  useEffect(() => {
    setCurrentGuildId(activeGuildId);
    persistGuildId(activeGuildId);
  }, [activeGuildId]);

  // Sync Tabs: If another tab updates the guild, this tab should follow suit.
  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key === GUILD_STORAGE_KEY) {
        const newId = event.newValue ? Number(event.newValue) : null;
        if (newId !== activeGuildId) {
          setActiveGuildId(newId);
        }
      }
    };

    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, [activeGuildId]);

  const applyGuildState = useCallback((guildList: Guild[]) => {
    const sortedGuilds = sortGuilds(guildList);
    setGuilds(sortedGuilds);

    // 1. PRIORITY: Check Local Storage (Client Session Preference)
    // This allows unique browsing sessions on different devices.
    const stored = readStoredGuildId();
    if (stored && sortedGuilds.some((guild) => guild.id === stored)) {
      setActiveGuildId(stored);
      return;
    }

    // 2. FALLBACK: Server State
    // Only trust the server's "active" flag if we have no local preference.
    const serverActive = sortedGuilds.find((guild) => guild.is_active);
    if (serverActive) {
      setActiveGuildId(serverActive.id);
      return;
    }

    // 3. FINAL FALLBACK: First available guild
    setActiveGuildId(sortedGuilds[0]?.id ?? null);
  }, []);

  const refreshGuilds = useCallback(async () => {
    if (!token || !user) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      return;
    }

    // Avoid setting loading=true on background refreshes if we already have data
    if (guilds.length === 0) setLoading(true);

    setError(null);
    try {
      const response = await apiClient.get<Guild[]>("/guilds/");
      applyGuildState(response.data);
    } catch (err) {
      console.error("Failed to load guilds", err);
      const axiosError = err as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      setError(detail ?? "Unable to load guilds.");
    } finally {
      setLoading(false);
    }
  }, [token, user, applyGuildState, guilds.length]);

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
    if (!user || !token) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      return;
    }
    void refreshGuilds();
  }, [user, token, refreshGuilds]);

  const switchGuild = useCallback(
    async (guildId: number) => {
      // Don't switch if we are already there
      if (!user || guildId === activeGuildId) {
        return;
      }

      try {
        // Tell backend we switched (for future default logins)
        await apiClient.post(`/guilds/${guildId}/switch`);

        // Update local state immediately so UI reacts
        setActiveGuildId(guildId);

        // Refresh data in background to ensure everything is synced
        await Promise.all([refreshGuilds(), refreshUser()]);
      } catch (err) {
        console.error("Failed to switch guild", err);
        throw err;
      }
    },
    [user, activeGuildId, refreshGuilds, refreshUser]
  );

  /**
   * Sync guild context from URL without full navigation.
   * Used by guild-scoped routes to sync context from URL params.
   * This is lighter weight than switchGuild - it doesn't call backend /switch
   * unless necessary, as the URL already contains the guild context.
   */
  const syncGuildFromUrl = useCallback(
    async (guildId: number) => {
      if (guildId === activeGuildId) {
        return;
      }

      // Update local state immediately
      setActiveGuildId(guildId);
      setCurrentGuildId(guildId);
      persistGuildId(guildId);

      // Background sync with backend to update "last used guild"
      try {
        await apiClient.post(`/guilds/${guildId}/switch`);
      } catch (err) {
        console.error("Failed to sync guild from URL", err);
        // Don't throw - the URL already has the correct guild context
      }
    },
    [activeGuildId]
  );

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
        const ordered: Guild[] = [];
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

      const response = await apiClient.post<Guild>("/guilds/", {
        name: trimmedName,
        description: description?.trim() || undefined,
      });

      await Promise.all([refreshGuilds(), refreshUser()]);

      return response.data;
    },
    [user, canCreateGuilds, refreshGuilds, refreshUser]
  );

  const updateGuildInState = useCallback((guild: Guild) => {
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

    if (guild.is_active) {
      setActiveGuildId(guild.id);
    }
  }, []);

  const activeGuild = useMemo(
    () => guilds.find((guild) => guild.id === activeGuildId) ?? null,
    [guilds, activeGuildId]
  );

  const value: GuildContextValue = {
    guilds,
    activeGuildId,
    activeGuild,
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
