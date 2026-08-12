/**
 * Who sees the Apps section, and when.
 *
 * The rules are about not promising anything: a member with no apps installed
 * has nothing to look at and nothing they could do about it, so the section is
 * absent entirely rather than empty. An admin in the same guild does have
 * something to do, so they get it with the `+`.
 *
 * Disabled apps belong in guild settings, not here — the sidebar shows what is
 * on.
 *
 * An admin-only app is hidden from members for the same reason an empty section
 * is: it has no sharing to widen, so the entry would refuse everyone who clicked
 * it. The server says which apps those are; this only honors the answer.
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

/** An app that opens the deployment's configured surface: no content of its
 *  own, and admin-only because the endpoint behind it is. */
const embedApp = (overrides: Partial<GuildAppRead> = {}) =>
  ({
    id: 7,
    name: "Automations",
    tool: null,
    embed_target: "advanced_tool",
    admin_only: true,
    enabled: true,
    config: {},
    ...overrides,
  }) as GuildAppRead;

const app = (overrides: Partial<GuildAppRead> = {}) =>
  ({
    id: 1,
    name: "Guild calendar",
    tool: "calendar",
    enabled: true,
    config: { calendar_id: 12 },
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

/**
 * Absence, waited for.
 *
 * The page renders through a router, so it renders nothing synchronously —
 * asserting an empty DOM the moment `render` returns passes before the section
 * has had a chance to appear, and would pass just as well if it were broken.
 * This waits for the section instead, and requires that it never arrives.
 */
const expectNoSection = () =>
  expect(screen.findByText("Apps", {}, { timeout: 400 })).rejects.toThrow();

beforeEach(() => {
  apps = [];
});

describe("AppsSection", () => {
  it("shows nothing to a member when the guild has no apps", async () => {
    render(false);
    await expectNoSection();
  });

  it("invites an admin to add one when the guild has no apps", async () => {
    render(true);
    expect(await screen.findByText("Apps")).toBeInTheDocument();
    expect(screen.getByLabelText("Add an app")).toBeInTheDocument();
  });

  it("lists installed apps for a member", async () => {
    apps = [app()];
    render(false);
    expect(await screen.findByText("Guild calendar")).toBeInTheDocument();
    // No add affordance: installing is a guild-admin action.
    expect(screen.queryByLabelText("Add an app")).toBeNull();
  });

  it("links an app to what it mounted", async () => {
    apps = [app()];
    render(false);
    const link = (await screen.findByText("Guild calendar")).closest("a");
    expect(link?.getAttribute("href")).toContain("/calendars/12");
  });

  it("hides a disabled app", async () => {
    // Turned off means gone from the sidebar; guild settings is where it comes
    // back, which is also the only place the switch lives.
    apps = [app({ enabled: false })];
    render(true);
    await screen.findByText("Apps");
    expect(screen.queryByText("Guild calendar")).toBeNull();
  });

  it("shows a member nothing when every app is disabled", async () => {
    apps = [app({ enabled: false })];
    render(false);
    await expectNoSection();
  });

  it("renders an app with nothing to link to without a link", async () => {
    apps = [app({ config: {} })];
    render(false);
    const entry = await screen.findByText("Guild calendar");
    expect(entry.closest("a")).toBeNull();
  });

  it("hides an admin-only app from a member", async () => {
    // Nothing it could offer them: its surface is minted admin-only, and there
    // are no grants to widen.
    apps = [embedApp()];
    render(false);
    await expectNoSection();
  });

  it("shows an admin-only app to an admin, at its own page", async () => {
    apps = [embedApp()];
    render(true);
    const link = (await screen.findByText("Automations")).closest("a");
    expect(link?.getAttribute("href")).toContain("/apps/7");
  });

  it("keeps listing shareable apps for a member alongside a hidden one", async () => {
    // The filter is per app, not a switch on the whole section.
    apps = [embedApp(), app()];
    render(false);
    expect(await screen.findByText("Guild calendar")).toBeInTheDocument();
    expect(screen.queryByText("Automations")).toBeNull();
  });
});
