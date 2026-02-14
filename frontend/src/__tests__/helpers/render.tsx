import { ReactElement } from "react";
import { vi } from "vitest";
import { render, RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  createMemoryHistory,
  RouterProvider,
} from "@tanstack/react-router";

import { AuthContext } from "@/hooks/useAuth";
import { GuildContext } from "@/hooks/useGuilds";
import { ServerContext } from "@/hooks/useServer";
import { ThemeContext } from "@/hooks/useTheme";
import { buildUser } from "@/__tests__/factories/user.factory";
import { buildGuild } from "@/__tests__/factories/guild.factory";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AuthOverrides = Partial<React.ComponentProps<typeof AuthContext.Provider>["value"]>;
type GuildOverrides = Partial<React.ComponentProps<typeof GuildContext.Provider>["value"]>;
type ServerOverrides = Partial<React.ComponentProps<typeof ServerContext.Provider>["value"]>;
type ThemeOverrides = Partial<React.ComponentProps<typeof ThemeContext.Provider>["value"]>;

interface ProviderOptions {
  auth?: AuthOverrides;
  guilds?: GuildOverrides;
  server?: ServerOverrides;
  theme?: ThemeOverrides;
  queryClient?: QueryClient;
}

interface RenderWithProvidersResult extends ReturnType<typeof render> {
  queryClient: QueryClient;
}

interface RenderPageOptions extends ProviderOptions {
  routerSearch?: Record<string, unknown>;
  initialRoute?: string;
}

// ---------------------------------------------------------------------------
// Query client factory
// ---------------------------------------------------------------------------

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Default context values
// ---------------------------------------------------------------------------

function buildDefaultAuth(): React.ComponentProps<typeof AuthContext.Provider>["value"] {
  return {
    user: buildUser(),
    token: "test-token",
    loading: false,
    isDeviceToken: false,
    login: vi.fn(),
    register: vi.fn(),
    completeOidcLogin: vi.fn(),
    logout: vi.fn(),
    refreshUser: vi.fn(),
  };
}

function buildDefaultGuilds(): React.ComponentProps<typeof GuildContext.Provider>["value"] {
  const guild = buildGuild();
  return {
    guilds: [guild],
    activeGuildId: 1,
    activeGuild: guild,
    loading: false,
    error: null,
    refreshGuilds: vi.fn(),
    switchGuild: vi.fn(),
    syncGuildFromUrl: vi.fn(),
    createGuild: vi.fn(),
    updateGuildInState: vi.fn(),
    reorderGuilds: vi.fn(),
    canCreateGuilds: true,
  };
}

function buildDefaultServer(): React.ComponentProps<typeof ServerContext.Provider>["value"] {
  return {
    serverUrl: null,
    isNativePlatform: false,
    isServerConfigured: true,
    loading: false,
    setServerUrl: vi.fn(),
    clearServerUrl: vi.fn(),
    testServerConnection: vi.fn(),
    getServerHostname: vi.fn().mockReturnValue(null),
  };
}

function buildDefaultTheme(): React.ComponentProps<typeof ThemeContext.Provider>["value"] {
  return {
    theme: "light",
    resolvedTheme: "light",
    setTheme: vi.fn(),
    toggleTheme: vi.fn(),
  };
}

// ---------------------------------------------------------------------------
// Provider wrapper
// ---------------------------------------------------------------------------

function buildWrapper(options: ProviderOptions = {}) {
  const queryClient = options.queryClient ?? createTestQueryClient();
  const auth = { ...buildDefaultAuth(), ...options.auth } as ReturnType<typeof buildDefaultAuth>;
  const guilds = { ...buildDefaultGuilds(), ...options.guilds } as ReturnType<
    typeof buildDefaultGuilds
  >;
  const server = { ...buildDefaultServer(), ...options.server } as ReturnType<
    typeof buildDefaultServer
  >;
  const theme = { ...buildDefaultTheme(), ...options.theme } as ReturnType<
    typeof buildDefaultTheme
  >;

  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ServerContext.Provider value={server}>
          <ThemeContext.Provider value={theme}>
            <AuthContext.Provider value={auth}>
              <GuildContext.Provider value={guilds}>{children}</GuildContext.Provider>
            </AuthContext.Provider>
          </ThemeContext.Provider>
        </ServerContext.Provider>
      </QueryClientProvider>
    );
  }

  return { Wrapper, queryClient };
}

// ---------------------------------------------------------------------------
// renderWithProviders
// ---------------------------------------------------------------------------

export function renderWithProviders(
  ui: ReactElement,
  options: ProviderOptions & Omit<RenderOptions, "wrapper"> = {}
): RenderWithProvidersResult {
  const { auth, guilds, server, theme, queryClient: qc, ...renderOptions } = options;
  const { Wrapper, queryClient } = buildWrapper({ auth, guilds, server, theme, queryClient: qc });

  const result = render(ui, { wrapper: Wrapper, ...renderOptions });

  return { ...result, queryClient };
}

// ---------------------------------------------------------------------------
// renderPage - wraps a page component in a TanStack Router
// ---------------------------------------------------------------------------

export function renderPage(
  PageComponent: React.ComponentType,
  options: RenderPageOptions & Omit<RenderOptions, "wrapper"> = {}
): RenderWithProvidersResult {
  const {
    auth,
    guilds,
    server,
    theme,
    queryClient: qc,
    routerSearch,
    initialRoute = "/",
    ...renderOptions
  } = options;

  const { Wrapper, queryClient } = buildWrapper({
    auth,
    guilds,
    server,
    theme,
    queryClient: qc,
  });

  const rootRoute = createRootRoute();

  const childRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: initialRoute,
    component: PageComponent as () => ReactElement,
    validateSearch: () => routerSearch ?? {},
  });

  const routeTree = rootRoute.addChildren([childRoute]);

  const history = createMemoryHistory({
    initialEntries: [initialRoute],
  });

  const router = createRouter({ routeTree, history });

  const result = render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
    renderOptions
  );

  return { ...result, queryClient };
}
