import { ReactNode, createContext, useCallback, useContext, useEffect, useState } from "react";
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

  useEffect(() => {
    setCurrentGuildId(activeGuildId);
    persistGuildId(activeGuildId);
  }, [activeGuildId]);

  const applyGuildState = useCallback((guildList: Guild[]) => {
    setGuilds(guildList);
    const serverActive = guildList.find((guild) => guild.is_active);
    if (serverActive) {
      setActiveGuildId(serverActive.id);
      return;
    }
    const stored = readStoredGuildId();
    if (stored && guildList.some((guild) => guild.id === stored)) {
      setActiveGuildId(stored);
      return;
    }
    setActiveGuildId(guildList[0]?.id ?? null);
  }, []);

  const refreshGuilds = useCallback(async () => {
    if (!token || !user) {
      setGuilds([]);
      setActiveGuildId(null);
      setError(null);
      return;
    }
    setLoading(true);
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
  }, [token, user, applyGuildState]);

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
      if (!user || guildId === activeGuildId) {
        return;
      }
      try {
        await apiClient.post(`/guilds/${guildId}/switch`);
        setActiveGuildId(guildId);
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
    [user, refreshGuilds, refreshUser]
  );

  const updateGuildInState = useCallback(
    (guild: Guild) => {
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
    },
    []
  );

  const value: GuildContextValue = {
    guilds,
    activeGuildId,
    activeGuild: guilds.find((guild) => guild.id === activeGuildId) ?? null,
    loading,
    error,
    refreshGuilds,
    switchGuild,
    createGuild,
    updateGuildInState,
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
