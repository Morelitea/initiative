/**
 * The way into the community directory, through the router the app ships.
 *
 * Three links make up that way in, and a test that mounts the page component
 * directly proves none of them: the generated route tree has to register
 * `/communities`, the route's component has to actually load (it is code-split,
 * so it arrives as its own chunk), and the entry in the guild rail has to point
 * at an address that tree resolves. Break any one of them and clicking the
 * entry renders nothing at all — which is indistinguishable, on screen, from a
 * button that does nothing.
 *
 * So each link is checked against the real article: the generated tree, the
 * route's own component, and the href the rail renders.
 */
import { createRouter } from "@tanstack/react-router";
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";
import { AppSidebar } from "@/components/AppSidebar";
import { GuildSidebar } from "@/components/guilds/GuildSidebar";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { GuildEntry } from "@/hooks/useGuilds";
import { routeTree } from "@/routeTree.gen";

import { buildGuild } from "./factories";
import { renderPage } from "./helpers/render";

const appConfig = vi.hoisted(() => ({ directory: true }));
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    billing: null,
    communityDirectoryEnabled: appConfig.directory,
    isLoading: false,
  }),
}));
vi.mock("@/lib/chesterToast", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

const directory = vi.fn();
vi.mock("@/hooks/useCommunities", () => ({
  useCommunityGuilds: (params: unknown) => directory(params),
  useJoinCommunityGuild: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const community: CommunityGuildRead = {
  id: 7,
  name: "Riverside Players",
  description: "Community theatre.",
  icon_url: null,
  banner_card_url: null,
  banner_color: null,
  categories: ["art"],
  member_count: 12,
  already_member: false,
};

const DIRECTORY_ROUTE_ID = "/_serverRequired/_authenticated/communities";

/** The router the app builds, from the generated tree rather than a tree
 *  assembled for the test — the registration is the thing under test. */
const router = createRouter({ routeTree });

const resolvedRouteId = (pathname: string): string => {
  const matches = router.matchRoutes({ pathname, search: {} }, { preload: true });
  return String(matches.at(-1)?.routeId ?? "__none__");
};

beforeEach(() => {
  vi.clearAllMocks();
  appConfig.directory = true;
  directory.mockReturnValue({
    data: { pages: [{ items: [community], total: 1 }] },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  });
});

describe("the community directory's way in", () => {
  it("is an address the shipped route tree serves", () => {
    expect(resolvedRouteId("/communities")).toBe(DIRECTORY_ROUTE_ID);
  });

  it("is where the rail's entry points", async () => {
    const guilds = [
      { ...buildGuild({ id: 1, name: "Alpha" }), accessType: "member" } as GuildEntry,
    ];
    renderPage(
      () => (
        <SidebarProvider>
          <GuildSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/g/$guildId", routeParams: { guildId: "1" }, guilds: { guilds } }
    );

    const link = await screen.findByRole("link", { name: "Join a community" });
    // The href the rail renders, put back through the shipped tree: an entry
    // pointing somewhere that tree does not serve is the failure this catches.
    expect(resolvedRouteId(new URL(link.getAttribute("href") ?? "", "http://x").pathname)).toBe(
      DIRECTORY_ROUTE_ID
    );
  });

  it("loads its page from its own chunk, searchable, with a card per community", async () => {
    const route = router.routesById[DIRECTORY_ROUTE_ID];
    const Page = route.options.component as React.ComponentType & {
      preload?: () => Promise<unknown>;
    };

    // The dynamic import the route is declared with. A moved page, a renamed
    // export, or a chunk that will not load fails here rather than at a click.
    await Page.preload?.();

    renderPage(Page, { initialRoute: "/communities" });

    expect(await screen.findByText("Riverside Players")).toBeInTheDocument();
    expect(screen.getByText("1 community")).toBeInTheDocument();
  });

  it("puts what narrows it in the sidebar, on this route and not the next", async () => {
    // The filters and the cards sit on opposite sides of the app layout, so
    // the shell has to switch the sidebar over on the way in — a page of cards
    // with no way to narrow them is the failure this catches.
    const { unmount } = renderPage(
      () => (
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/communities" }
    );
    expect(await screen.findByLabelText("Search communities")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tabletop RPG" })).toBeInTheDocument();
    unmount();

    renderPage(
      () => (
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/my-projects" }
    );
    expect(await screen.findByRole("link", { name: "My Projects" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Search communities")).not.toBeInTheDocument();
  });

  it("keeps the personal sidebar where the owner runs no directory", async () => {
    // The page says there is nothing here; a search box and twelve shelves
    // beside it would be offering to narrow something that does not exist.
    appConfig.directory = false;
    renderPage(
      () => (
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      ),
      { initialRoute: "/communities" }
    );

    expect(await screen.findByRole("link", { name: "My Projects" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Search communities")).not.toBeInTheDocument();
  });
});
