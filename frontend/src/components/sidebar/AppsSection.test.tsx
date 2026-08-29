/**
 * Who sees the Apps section, and when.
 *
 * The section shows for everyone, because everyone can do something with it:
 * an admin adds an app, and a member browses the same shelf to see what exists
 * and who to ask for it. What differs is the invitation at the bottom.
 *
 * Disabled apps belong in guild settings, not here — the sidebar shows what is
 * on.
 *
 * An admin-only app is hidden from members for the same reason an empty section
 * is: it has no sharing to widen, so the entry would refuse everyone who clicked
 * it. The server says which apps those are; this only honors the answer.
 *
 * And every visible entry leads somewhere: an app with a surface opens it, an
 * app with a credential to supply opens that form, and an app with neither
 * waits under "show more" rather than spending a row on a dead click.
 */
import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/__tests__/helpers/render";
import type { GuildAppRead } from "@/api/generated/initiativeAPI.schemas";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

import { AppsSection } from "./AppsSection";

let apps: Partial<GuildAppRead>[] = [];

vi.mock("@/hooks/useGuildApps", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useGuildApps")>()),
  useGuildApps: () => ({ data: { items: apps }, isLoading: false }),
}));

const app = (overrides: Partial<GuildAppRead> = {}) =>
  ({
    id: 1,
    name: "Guild calendar",
    tool: "calendar",
    enabled: true,
    artifacts: [{ type: "calendar", id: 12 }],
    ...overrides,
  }) as GuildAppRead;

// The section is built from sidebar primitives, so it needs the providers it
// would have in the real shell.
const render = (isGuildAdmin: boolean) =>
  renderPage(() => (
    <TooltipProvider>
      <SidebarProvider>
        <AppsSection isGuildAdmin={isGuildAdmin} open onOpenChange={() => {}} />
      </SidebarProvider>
    </TooltipProvider>
  ));

beforeEach(() => {
  apps = [];
});

describe("AppsSection", () => {
  it("points a member at the store when the guild has no apps", async () => {
    // They cannot add one, but they can look and ask, so the shelf is worth
    // pointing at rather than hiding.
    render(false);
    expect(await screen.findByText("Apps")).toBeInTheDocument();
    expect(screen.getByText("Browse the app store")).toBeInTheDocument();
    expect(screen.queryByText("Add an app")).toBeNull();
  });

  it("invites an admin to add one when the guild has no apps", async () => {
    render(true);
    expect(await screen.findByText("Apps")).toBeInTheDocument();
    expect(screen.getByText("Add an app")).toBeInTheDocument();
    expect(screen.queryByText("Browse the app store")).toBeNull();
  });

  it("lists installed apps for a member", async () => {
    apps = [app()];
    render(false);
    expect(await screen.findByText("Guild calendar")).toBeInTheDocument();
    // No add affordance: installing is a guild-admin action.
    expect(screen.queryByText("Add an app")).toBeNull();
    expect(screen.getByText("Browse the app store")).toBeInTheDocument();
  });

  it("links an app to what it mounted", async () => {
    apps = [app()];
    render(false);
    const link = (await screen.findByText("Guild calendar")).closest("a");
    // The list, not one of them: a member may add calendars to the app, so its
    // entry leads to everything it holds.
    expect(link?.getAttribute("href")).toContain("/calendars");
    expect(link?.getAttribute("href")).not.toContain("/calendars/12");
  });

  it("still links a tool-instance app that holds nothing yet", async () => {
    // Its home is where the first one gets made, so an empty app is the one
    // that most needs a row.
    apps = [app({ artifacts: [] })];
    render(false);
    const link = (await screen.findByText("Guild calendar")).closest("a");
    expect(link?.getAttribute("href")).toContain("/calendars");
  });

  it("hides a disabled app", async () => {
    // Turned off means gone from the sidebar; guild settings is where it comes
    // back, which is also the only place the switch lives.
    apps = [app({ enabled: false })];
    render(true);
    await screen.findByText("Apps");
    expect(screen.queryByText("Guild calendar")).toBeNull();
  });

  it("still offers the store to a member when every app is disabled", async () => {
    apps = [app({ enabled: false })];
    render(false);
    expect(await screen.findByText("Browse the app store")).toBeInTheDocument();
    expect(screen.queryByText("Guild calendar")).toBeNull();
  });

  it("opens a service app's own page", async () => {
    apps = [
      app({
        id: 7,
        name: "Automations",
        tool: null,
        artifacts: [],
        definition: { embeds: [{ id: "automations", path: "/embed" }] },
      }),
    ];
    render(false);
    const link = (await screen.findByText("Automations")).closest("a");
    expect(link?.getAttribute("href")).toContain("/apps/7");
  });

  it("draws the listing's artwork rather than a generic icon", async () => {
    apps = [app({ avatar_url: "/marketplace/calendar.svg" })];
    render(false);
    const entry = await screen.findByText("Guild calendar");
    const artwork = entry.closest("a")?.querySelector("img");
    expect(artwork?.getAttribute("src")).toBe("/marketplace/calendar.svg");
  });

  it("folds an app with nothing to open under 'show more'", async () => {
    // An app that mounts no tool, declares no surface this reader may open and
    // asks for no credential has nowhere to lead, so it is not worth a row
    // until asked for.
    apps = [app({ name: "Widgets only", tool: null, artifacts: [] })];
    render(false);
    await screen.findByText("Apps");
    expect(screen.queryByText("Widgets only")).toBeNull();

    (await screen.findByText("1 more")).click();
    const entry = await screen.findByText("Widgets only");
    expect(entry.closest("a")).toBeNull();
  });

  it("keeps the add affordance below the apps, 'show more' included", async () => {
    // Same shape as the initiatives list: adding one is always in the same
    // place, whether or not the collapsed apps are expanded.
    apps = [app(), app({ id: 2, name: "Widgets only", tool: null, artifacts: [] })];
    render(true);
    const add = await screen.findByText("Add an app");
    const more = await screen.findByText("1 more");
    // eslint-disable-next-line no-bitwise -- DOCUMENT_POSITION_FOLLOWING
    expect(more.compareDocumentPosition(add) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps an app that only has a credential to supply in the list", async () => {
    apps = [
      app({
        id: 9,
        name: "GitHub",
        tool: null,
        artifacts: [],
        definition: { connections: [{ id: "token", scope: "interactive" }] },
      }),
    ];
    render(false);
    // Listed, and not behind "show more" — there is something to open.
    expect(await screen.findByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByText("1 more")).toBeNull();
  });

  it("gives every app a settings gear, whatever else its entry does", async () => {
    // Three shapes of entry — a page, a credential form, nothing at all — and
    // the gear is on all of them, because every app has something a person may
    // want to check or take back.
    apps = [
      app(),
      app({
        id: 9,
        name: "GitHub",
        tool: null,
        artifacts: [],
        definition: { connections: [{ id: "token", scope: "interactive" }] },
      }),
    ];
    render(false);
    await screen.findByText("Guild calendar");
    expect(screen.getByLabelText("Guild calendar settings")).toBeInTheDocument();
    expect(screen.getByLabelText("GitHub settings")).toBeInTheDocument();
  });

  it("gives the gear to an app with nothing to open, once it is shown", async () => {
    apps = [app({ name: "Widgets only", tool: null, artifacts: [] })];
    render(false);
    (await screen.findByText("1 more")).click();
    expect(await screen.findByLabelText("Widgets only settings")).toBeInTheDocument();
  });
});
