import {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { AxiosError } from "axios";
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
  createGuild: (input: { name: string; description?: string }) => Promise<Guild>;
  updateGuildInState: (guild: Guild) => void;
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

export const GuildProvider = ({ children }: { children: ReactNode }) => {
  const { user, token, refreshUser } = useAuth();
  const [guilds, setGuilds] = useState<Guild[]>([]);
  const [activeGuildId, setActiveGuildId] = useState<number | null>(readStoredGuildId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setGuilds(guildList);

    // 1. PRIORITY: Check Local Storage (Client Session Preference)
    // This allows unique browsing sessions on different devices.
    const stored = readStoredGuildId();
    if (stored && guildList.some((guild) => guild.id === stored)) {
      setActiveGuildId(stored);
      return;
    }

    // 2. FALLBACK: Server State
    // Only trust the server's "active" flag if we have no local preference.
    const serverActive = guildList.find((guild) => guild.is_active);
    if (serverActive) {
      setActiveGuildId(serverActive.id);
      return;
    }

    // 3. FINAL FALLBACK: First available guild
    setActiveGuildId(guildList[0]?.id ?? null);
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
      return replaced ? next : prev.concat(guild);
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
    createGuild,
    updateGuildInState,
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
