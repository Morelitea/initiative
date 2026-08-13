/**
 * Browsing the catalog.
 *
 * The load-bearing detail is where "already installed" comes from. The catalog
 * is platform-level and holds nothing about this guild, so the badge has to be
 * derived from the guild's own dashboards — matched on the listing uid an
 * install pins, not on the name or the public id.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { MarketplaceListingSummary } from "@/api/generated/initiativeAPI.schemas";

import { MarketplaceBrowsePage } from "./MarketplaceBrowsePage";

const listingsFor = vi.fn();
let installed: Record<string, number> = {};

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListings: (params: unknown) => listingsFor(params),
}));

let installedFailed = false;
let installedApps: { listing_uid: string }[] = [];

vi.mock("@/hooks/useDashboards", () => ({
  useInstalledListings: () => ({
    data: installedFailed ? undefined : { counts: installed },
    isError: installedFailed,
  }),
}));

vi.mock("@/hooks/useGuildApps", () => ({
  useGuildApps: () => ({
    data: installedFailed ? undefined : { items: installedApps },
    isError: installedFailed,
  }),
}));

const listing = (overrides: Partial<MarketplaceListingSummary> = {}) =>
  ({
    uid: "SPRNT000000001",
    public_id: "core.sprint",
    kind: "dashboard",
    source: "builtin",
    name: "Sprint health",
    publisher: "Initiative",
    description: "How the sprint is going.",
    avatar_url: "/marketplace/sprint.svg",
    images: [],
    installs_count: 0,
    available: true,
    installable: true,
    latest_version: { version: "1.0.0", compatible: true, published_at: "" },
    updated_at: "",
    ...overrides,
  }) as MarketplaceListingSummary;

beforeEach(() => {
  installed = {};
  installedApps = [];
  installedFailed = false;
  listingsFor.mockReturnValue({
    data: { items: [listing()], total: 1 },
    isLoading: false,
  });
});

describe("MarketplaceBrowsePage", () => {
  it("shows a card per listing", async () => {
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText("Sprint health")).toBeInTheDocument();
    // Attribution rides along with how the listing got here, so a card never
    // shows an author's name on its own.
    expect(screen.getByText("by Initiative")).toBeInTheDocument();
  });

  it("asks the catalog only for dashboards", async () => {
    // Defaulted by the page itself: `useSearch({ strict: false })` does not run
    // the route's validation, so a page that leaned on it would drop the filter
    // and mix apps into the grid.
    renderPage(MarketplaceBrowsePage);
    await screen.findByText("Sprint health");
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ kind: "dashboard" }));
  });

  it("asks for apps on the apps shelf", async () => {
    renderPage(MarketplaceBrowsePage, { routerSearch: { kind: "app" } });
    await screen.findByText("Sprint health");
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ kind: "app" }));
  });

  it("marks an installed app on the apps shelf", async () => {
    // Each shelf asks its own tool: the dashboards aggregate knows nothing
    // about apps, so reading installed state from it here would report every
    // app as not installed.
    installedApps = [{ listing_uid: "SPRNT000000001" }];
    renderPage(MarketplaceBrowsePage, { routerSearch: { kind: "app" } });
    expect(await screen.findByText("Installed")).toBeInTheDocument();
  });

  it("does not read app installs from the dashboard aggregate", async () => {
    installed = { SPRNT000000001: 1 };
    installedApps = [];
    renderPage(MarketplaceBrowsePage, { routerSearch: { kind: "app" } });
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("marks a listing this guild already installed", async () => {
    // Counted server-side over every dashboard. Deriving this from the
    // paginated dashboard list would mark some installs and miss the rest once
    // a guild has more dashboards than fit on a page.
    installed = { SPRNT000000001: 1 };
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText("Installed")).toBeInTheDocument();
  });

  it("does not mark a listing whose uid nobody here pinned", async () => {
    installed = { SMTHNG00000001: 2 };
    renderPage(MarketplaceBrowsePage);
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("searches the catalog rather than filtering the page", async () => {
    // Paging means the answer is not all on screen, so the query has to reach
    // the server.
    const user = userEvent.setup();
    renderPage(MarketplaceBrowsePage);
    await user.type(await screen.findByRole("textbox"), "burndown");

    await waitFor(() =>
      expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ q: "burndown" }))
    );
  });

  it("says so rather than marking everything uninstalled when the check fails", async () => {
    // "We do not know" and "you have none of these" look identical on a card,
    // and only one of them is true — so the page says which.
    installedFailed = true;
    renderPage(MarketplaceBrowsePage);
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
    expect(screen.getByText(/couldn't check which of these/i)).toBeInTheDocument();
  });

  it("says nothing extra when the check succeeds", async () => {
    installed = { SPRNT000000001: 1 };
    renderPage(MarketplaceBrowsePage);
    await screen.findByText("Installed");
    expect(screen.queryByText(/couldn't check which of these/i)).toBeNull();
  });

  it("does not present a failed catalog as an empty one", async () => {
    // "Nothing to offer" would send someone looking for listings that exist.
    listingsFor.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText(/marketplace unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/nothing here yet/i)).toBeNull();
  });

  it("says so when a search matches nothing", async () => {
    listingsFor.mockReturnValue({ data: { items: [], total: 0 }, isLoading: false });
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText(/nothing here yet|no matches/i)).toBeInTheDocument();
  });
});
