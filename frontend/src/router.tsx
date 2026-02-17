import { createRouter } from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";

import { routeTree } from "./routeTree.gen";
import type { Guild } from "./types/api";

// Define the router context types
export interface AuthContextValue {
  user: { id: number; email: string; full_name?: string | null } | null;
  token: string | null;
  loading: boolean;
  isDeviceToken: boolean;
  login: (payload: { email: string; password: string; deviceName?: string }) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name?: string;
    inviteCode?: string;
  }) => Promise<unknown>;
  completeOidcLogin: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export interface GuildContextValue {
  guilds: Guild[];
  activeGuildId: number | null;
  activeGuild: Guild | null;
  loading: boolean;
  error: string | null;
  refreshGuilds: () => Promise<void>;
  switchGuild: (guildId: number) => Promise<void>;
  createGuild: (input: { name: string; description?: string }) => Promise<unknown>;
  updateGuildInState: (guild: Guild) => void;
  reorderGuilds: (guildIds: number[]) => void;
  canCreateGuilds: boolean;
}

export interface ServerContextValue {
  serverUrl: string | null;
  isNativePlatform: boolean;
  isServerConfigured: boolean;
  loading: boolean;
  setServerUrl: (url: string) => Promise<void>;
  clearServerUrl: () => Promise<void>;
  testServerConnection: (url: string) => Promise<{ valid: boolean; error?: string }>;
  getServerHostname: () => string | null;
}

export interface RouterContext {
  queryClient: QueryClient;
  auth: AuthContextValue | undefined;
  guilds: GuildContextValue | undefined;
  server: ServerContextValue | undefined;
}

// Create the router instance
export const router = createRouter({
  routeTree,
  context: {
    queryClient: undefined!,
    auth: undefined,
    guilds: undefined,
    server: undefined,
  },
  defaultPreload: "intent",
  defaultPreloadStaleTime: 30_000,
  defaultStaleTime: 0,
  scrollRestoration: true,
  defaultViewTransition: true,
});

// Register the router for type safety
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
