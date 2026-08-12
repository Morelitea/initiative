/**
 * Reading a listing, and getting back out.
 *
 * The shelf you were browsing has to survive the round trip. Both ways out of
 * this page lead to the marketplace, and each one has to carry the kind —
 * otherwise an admin browsing apps clicks a listing, comes back, and is looking
 * at dashboards. The error route is the one that got missed first, which is why
 * it is pinned here alongside the ordinary one.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";

import { MarketplaceListingPage } from "./MarketplaceListingPage";

let listing: Partial<MarketplaceListingDetail> | undefined;
let failed = false;

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListing: () => ({ data: listing, isError: failed }),
}));
vi.mock("@/hooks/useDashboards", () => ({ useWidgetCatalog: () => ({ data: undefined }) }));
vi.mock("@/hooks/useGuilds", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuilds")>()),
  useGuilds: () => ({ activeGuild: { role: "admin" } }),
}));

const appListing = () =>
  ({
    uid: "GLDCAL00000001",
    public_id: "core.guild-calendar",
    kind: "app",
    name: "Guild calendar",
    publisher: "Initiative",
    description: "The guild's own events.",
    avatar_url: "/marketplace/cal.svg",
    images: [],
    installs_count: 0,
    available: true,
    installable: true,
    versions: [],
    updated_at: "",
  }) as unknown as MarketplaceListingDetail;

/** The href of the link back to the marketplace, whichever route rendered it. */
const backHref = () =>
  screen
    .getAllByRole("link")
    .map((link) => link.getAttribute("href"))
    .find((href) => href?.includes("/marketplace") && !href.includes("core."));

beforeEach(() => {
  listing = appListing();
  failed = false;
});

describe("MarketplaceListingPage", () => {
  it("returns to the shelf it was opened from", async () => {
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });
    await screen.findByRole("heading", { name: "Guild calendar" });
    expect(backHref()).toContain("kind=app");
  });

  it("returns to the shelf when the listing failed to load", async () => {
    // The way out of an error state is the one people actually take, and it was
    // the one that dropped the shelf.
    failed = true;
    listing = undefined;
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });
    await screen.findByText(/listing not found/i);
    expect(backHref()).toContain("kind=app");
  });

  it("falls back to the listing's own kind on a direct link", async () => {
    // Arrived without a shelf in the URL: the listing itself says which one it
    // belongs to.
    renderPage(MarketplaceListingPage);
    await screen.findByRole("heading", { name: "Guild calendar" });
    expect(backHref()).toContain("kind=app");
  });

  it("offers no canvas preview for an app", async () => {
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });
    await screen.findByRole("heading", { name: "Guild calendar" });
    // An app mounts a tool; there is no definition to draw.
    expect(screen.queryByText("Preview")).toBeNull();
  });
});
