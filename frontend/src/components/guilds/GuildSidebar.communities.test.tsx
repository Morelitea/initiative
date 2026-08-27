/**
 * Clicking the way into the community directory has to land on the directory.
 *
 * The sidebar's own tests assert the entry's address, which is half of it: the
 * app renders the page behind that address through the router, and a click that
 * resolves to nothing on screen is indistinguishable from a button that does
 * not work. So this mounts both halves — the rail the entry sits in and the
 * route the directory lives at — and clicks the way a person does, then looks
 * for the two things the page is: a search box, and cards.
 */
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderWithProviders } from "@/__tests__/helpers/render";
import type { CommunityGuildRead } from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { GuildEntry } from "@/hooks/useGuilds";
import { CommunitiesPage } from "@/pages/communities/CommunitiesPage";

import { GuildSidebar } from "./GuildSidebar";

vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: null }) }));
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
  icon_base64: null,
  categories: ["art"],
  member_count: 12,
  already_member: false,
};

/** The two routes this exercise needs: somewhere with the rail on it, and the
 *  directory the rail points at. */
const mount = () => {
  const rootRoute = createRootRoute();
  const guildRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/g/$guildId",
    component: () => (
      <SidebarProvider>
        <GuildSidebar />
      </SidebarProvider>
    ),
  });
  const directoryRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/communities",
    component: CommunitiesPage,
    validateSearch: (search: Record<string, unknown>) => search,
  });
  const router = createRouter({
    routeTree: rootRoute.addChildren([guildRoute, directoryRoute]),
    history: createMemoryHistory({ initialEntries: ["/g/1"] }),
  });

  const guilds = [{ ...buildGuild({ id: 1, name: "Alpha" }), accessType: "member" } as GuildEntry];
  return {
    router,
    ...renderWithProviders(<RouterProvider router={router} />, {
      guilds: { guilds, activeGuildId: 1 },
    }),
  };
};

beforeEach(() => {
  vi.clearAllMocks();
  directory.mockReturnValue({
    data: { pages: [{ items: [community], total: 1 }] },
    isLoading: false,
    isError: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  });
});

describe("the rail's way into the community directory", () => {
  it("opens the directory, searchable, with a card per community", async () => {
    const { router } = mount();

    await userEvent.click(await screen.findByRole("link", { name: "Join a community" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/communities"));
    expect(await screen.findByLabelText("Search communities")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Categories" })).toBeInTheDocument();
    expect(screen.getByText("Riverside Players")).toBeInTheDocument();
  });
});
