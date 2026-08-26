import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { type RenderOptions, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { buildGuild } from "@/__tests__/factories/guild.factory";
import { buildUser } from "@/__tests__/factories/user.factory";
import { AuthContext } from "@/hooks/useAuth";
import { GuildContext } from "@/hooks/useGuilds";
import { ServerContext } from "@/hooks/useServer";
import { ThemeContext } from "@/hooks/useTheme";

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

interface RenderPageResult extends RenderWithProvidersResult {
  /** The memory router the page is mounted in — read
   *  `router.state.location.pathname` to assert where a flow navigated. */
  router: ReturnType<typeof createRouter>;
}

interface RenderPageOptions extends ProviderOptions {
  routerSearch?: Record<string, unknown>;
  /** The route the page is mounted at. Use `$param` segments for a page that
   *  reads `useParams`, and supply their values via {@link routeParams}. */
  initialRoute?: string;
  /** Values for the `$param` segments in {@link initialRoute}. */
  routeParams?: Record<string, string>;
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
    getServerOrigin: vi.fn().mockReturnValue("http://localhost"),
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
): RenderPageResult {
  const {
    auth,
    guilds,
    server,
    theme,
    queryClient: qc,
    routerSearch,
    initialRoute = "/",
    routeParams,
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
    // `routerSearch` seeds the first render only. Once the page navigates, its
    // own params win — otherwise a page that reads and rewrites the URL (say,
    // correcting an out-of-range `page`) could never be observed changing it.
    validateSearch: (search: Record<string, unknown>) =>
      Object.keys(search).length > 0 ? search : (routerSearch ?? {}),
  });

  const routeTree = rootRoute.addChildren([childRoute]);

  // The route pattern carries `$param` placeholders; the history entry needs
  // them filled in, or nothing matches.
  const initialEntry = routeParams
    ? Object.entries(routeParams).reduce(
        (path, [name, value]) => path.replaceAll(`$${name}`, value),
        initialRoute
      )
    : initialRoute;

  const history = createMemoryHistory({
    initialEntries: [initialEntry],
  });

  const router = createRouter({ routeTree, history });

  const result = render(
    <Wrapper>
      <RouterProvider router={router} />
    </Wrapper>,
    renderOptions
  );

  return { ...result, queryClient, router };
}
