import type { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";

import type { GuildRead, UserRead } from "@/api/generated/initiativeAPI.schemas";

import { routeTree } from "./routeTree.gen";

// Define the router context types
export interface AuthContextValue {
  user: UserRead | null;
  token: string | null;
  loading: boolean;
  isDeviceToken: boolean;
  login: (payload: { email: string; password: string; deviceName?: string }) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    username: string;
    full_name?: string;
    inviteCode?: string;
  }) => Promise<unknown>;
  completeOidcLogin: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export interface GuildContextValue {
  guilds: GuildRead[];
  activeGuildId: number | null;
  activeGuild: GuildRead | null;
  loading: boolean;
  error: string | null;
  refreshGuilds: () => Promise<void>;
  switchGuild: (guildId: number) => Promise<void>;
  /** Push the server-held guild context + local state for a guild URL.
   * Awaited in the /c/$guildId beforeLoad so child routes can't fetch
   * before the context lands. Idempotent. */
  syncGuildFromUrl: (guildId: number) => Promise<void>;
  createGuild: (input: { name: string; description?: string }) => Promise<unknown>;
  updateGuildInState: (guild: GuildRead) => void;
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

  interface StaticDataRouteOption {
    /**
     * Whether this route lays itself out against the window rather than inside
     * the app's reading container.
     *
     * Almost every screen here is a document in a centred column, and the shell
     * supplies that column. A few are a surface instead — a wiki is the one
     * today — where the chrome belongs against the edges and the page finds its
     * own measure inside. Declared on the route because the shell has to know
     * before the page renders.
     */
    fullBleed?: boolean;
  }
}
