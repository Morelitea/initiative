/**
 * Reading a listing, and getting back out.
 *
 * The shelf you were browsing has to survive the round trip. Both ways out of
 * this page lead to the marketplace, and each one has to carry the kind —
 * otherwise an admin browsing apps clicks a listing, comes back, and is looking
 * at dashboards. The error route is the one that got missed first, which is why
 * it is pinned here alongside the ordinary one.
 *
 * A member reads the same page as an admin. What changes is the ending: they
 * cannot install, so the page names who can instead of offering a button that
 * would be refused.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { MarketplaceListingDetail } from "@/api/generated/initiativeAPI.schemas";

import { MarketplaceListingPage } from "./MarketplaceListingPage";

let listing: Partial<MarketplaceListingDetail> | undefined;
let failed = false;
let guildRole = "admin";
let installedUids: string[] = [];
let installsState: "ready" | "loading" | "error" = "ready";

vi.mock("@/hooks/useMarketplace", () => ({
  useMarketplaceListing: () => ({ data: listing, isError: failed }),
}));
vi.mock("@/hooks/useDashboards", () => ({ useWidgetCatalog: () => ({ data: undefined }) }));
vi.mock("@/hooks/useGuilds", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuilds")>()),
  useGuilds: () => ({ activeGuild: { role: guildRole } }),
}));
vi.mock("@/hooks/useGuildApps", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuildApps")>()),
  useGuildApps: () => ({
    data:
      installsState === "ready"
        ? { items: installedUids.map((uid) => ({ listing_uid: uid })) }
        : undefined,
    isLoading: installsState === "loading",
    isError: installsState === "error",
  }),
}));

const appListing = () =>
  ({
    uid: "GLDCAL00000001",
    public_id: "core.guild-calendar",
    kind: "app",
    source: "builtin",
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
  guildRole = "admin";
  installedUids = [];
  installsState = "ready";
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

  it("answers who wrote it before the install button", async () => {
    // The same sentence the card showed, on the page where the decision is
    // actually made.
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });
    await screen.findByRole("heading", { name: "Guild calendar" });
    expect(screen.getByText("by Initiative")).toBeInTheDocument();
  });

  it("names the publisher of a listing that did not ship with this build", async () => {
    listing = {
      ...appListing(),
      source: "operator",
      publisher: "Acme Widgets",
    } as unknown as MarketplaceListingDetail;
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });
    await screen.findByRole("heading", { name: "Guild calendar" });
    expect(screen.getByText("by Acme Widgets")).toBeInTheDocument();
  });

  it("offers no canvas preview for an app", async () => {
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });
    await screen.findByRole("heading", { name: "Guild calendar" });
    // An app mounts a tool; there is no definition to draw.
    expect(screen.queryByText("Preview")).toBeNull();
  });

  it("tells a member who can add an app they cannot", async () => {
    guildRole = "member";
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });

    expect(await screen.findByText("Ask a guild admin to add this app.")).toBeInTheDocument();
    // The button is present but refuses, rather than being hidden: seeing what
    // the app offers is the point of letting them in here.
    expect(screen.getByRole("button", { name: /Add to guild/ })).toBeDisabled();
  });

  it("says an app is already installed instead of offering it again", async () => {
    installedUids = ["GLDCAL00000001"];
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });

    expect(await screen.findByText("Installed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add to guild/ })).toBeNull();
  });

  it("does not tell a member to ask for an app the guild already has", async () => {
    guildRole = "member";
    installedUids = ["GLDCAL00000001"];
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });

    expect(await screen.findByText("Installed")).toBeInTheDocument();
    expect(screen.queryByText("Ask a guild admin to add this app.")).toBeNull();
  });

  it("does not guess at installed state while it is still loading", async () => {
    // Neither answer is known yet, so neither is claimed: no badge saying it is
    // there, and no offer to add something the guild may already have.
    installsState = "loading";
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });

    await screen.findByRole("heading", { name: "Guild calendar" });
    expect(screen.queryByText("Installed")).toBeNull();
    expect(screen.getByRole("button", { name: /Add to guild/ })).toBeDisabled();
    expect(screen.queryByText("Ask a guild admin to add this app.")).toBeNull();
  });

  it("says so when it could not check, rather than implying not installed", async () => {
    installsState = "error";
    guildRole = "member";
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });

    expect(
      await screen.findByText("Could not check whether this app is already added.")
    ).toBeInTheDocument();
    // The "go ask an admin" line asserts the guild does not have it, which is
    // exactly what failed to load.
    expect(screen.queryByText("Ask a guild admin to add this app.")).toBeNull();
  });

  it("does not offer an admin an install it cannot rule out as a duplicate", async () => {
    // An admin *may* install, so only the unknown state holds the button back
    // here — the guild may already have this, and the server would refuse.
    installsState = "error";
    renderPage(MarketplaceListingPage, { routerSearch: { kind: "app" } });

    await screen.findByRole("heading", { name: "Guild calendar" });
    expect(screen.getByRole("button", { name: /Add to guild/ })).toBeDisabled();
  });
});
