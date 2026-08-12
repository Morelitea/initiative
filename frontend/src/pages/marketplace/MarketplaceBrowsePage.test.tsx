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
import type {
  DashboardSummary,
  MarketplaceListingSummary,
} from "@/api/generated/initiativeAPI.schemas";

import { MarketplaceBrowsePage } from "./MarketplaceBrowsePage";

const listingsFor = vi.fn();
let dashboards: Partial<DashboardSummary>[] = [];

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListings: (params: unknown) => listingsFor(params),
}));

vi.mock("@/hooks/useDashboards", () => ({
  useDashboardsList: () => ({ data: { items: dashboards } }),
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
  dashboards = [];
  listingsFor.mockReturnValue({
    data: { items: [listing()], total: 1 },
    isLoading: false,
  });
});

describe("MarketplaceBrowsePage", () => {
  it("shows a card per listing", async () => {
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText("Sprint health")).toBeInTheDocument();
    expect(screen.getByText("Initiative")).toBeInTheDocument();
  });

  it("asks the catalog only for dashboards", async () => {
    renderPage(MarketplaceBrowsePage);
    await screen.findByText("Sprint health");
    expect(listingsFor).toHaveBeenCalledWith(expect.objectContaining({ kind: "dashboard" }));
  });

  it("marks a listing this guild already installed", async () => {
    // Matched on the uid an install pins — the catalog says nothing about who
    // installed what, so this can only come from the guild's own dashboards.
    dashboards = [{ id: 1, listing_uid: "SPRNT000000001" } as Partial<DashboardSummary>];
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText("Installed")).toBeInTheDocument();
  });

  it("does not mark a listing whose uid nobody here pinned", async () => {
    dashboards = [{ id: 1, listing_uid: "SMTHNG00000001" } as Partial<DashboardSummary>];
    renderPage(MarketplaceBrowsePage);
    await screen.findByText("Sprint health");
    expect(screen.queryByText("Installed")).toBeNull();
  });

  it("does not mark a dashboard that was authored here", async () => {
    dashboards = [{ id: 1, listing_uid: null } as Partial<DashboardSummary>];
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

  it("says so when a search matches nothing", async () => {
    listingsFor.mockReturnValue({ data: { items: [], total: 0 }, isLoading: false });
    renderPage(MarketplaceBrowsePage);
    expect(await screen.findByText(/nothing here yet|no matches/i)).toBeInTheDocument();
  });
});
