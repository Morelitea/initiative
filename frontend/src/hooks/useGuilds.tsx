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
import { getItem, setItem, removeItem } from "@/lib/storage";
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
  // Start as true - we're loading until first fetch completes (or until we know we shouldn't fetch)
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const reorderDebounceRef = useRef<number | null>(null);
  const pendingOrderRef = useRef<number[] | null>(null);
  const hasFetchedRef = useRef(false);

  const canCreateGuilds = user?.can_create_guilds ?? true;

  // Sync API Client whenever ID changes
  useEffect(() => {
    setCurrentGuildId(activeGuildId);
    persistGuildId(activeGuildId);
  }, [activeGuildId]);

  const applyGuildState = useCallback((guildList: Guild[]) => {
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
    if (!token || !user) {
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
      const response = await apiClient.get<Guild[]>("/guilds/");
      hasFetchedRef.current = true;
      applyGuildState(response.data);
    } catch (err) {
      console.error("Failed to load guilds", err);
      const axiosError = err as AxiosError<{ detail?: string }>;
      const detail = axiosError.response?.data?.detail;
      setError(detail ?? "Unable to load guilds.");
    } finally {
      setLoading(false);
    }
  }, [token, user, applyGuildState]);

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
      setLoading(false);
      hasFetchedRef.current = false;
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

      // Update local state immediately so UI reacts
      setActiveGuildId(guildId);

      // Refresh data in background to ensure everything is synced
      await Promise.all([refreshGuilds(), refreshUser()]);
    },
    [user, activeGuildId, refreshGuilds, refreshUser]
  );

  /**
   * Sync guild context from URL without full navigation.
   * Used by guild-scoped routes to sync context from URL params.
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
