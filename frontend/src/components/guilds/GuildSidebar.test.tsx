/**
 * Reordering guilds on a touch screen.
 *
 * Touch has one press-and-hold, and the context menu owns it. Wiring a drag
 * sensor to the same gesture meant a long press on a guild started a reorder
 * instead of opening the menu, so the menu was unreachable on a phone. Touch
 * dragging now waits behind an explicit "Reorder guilds" action, and while it
 * is on a tap moves the guild rather than switching to it.
 *
 * A guild reached through a temporary access grant is not part of the user's
 * order, so it offers no reorder action.
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { GuildEntry } from "@/hooks/useGuilds";

import { GuildSidebar } from "./GuildSidebar";

const entry = (overrides: Partial<GuildEntry> = {}): GuildEntry =>
  ({ ...buildGuild(), accessType: "member", ...overrides }) as GuildEntry;

const setup = (guilds: GuildEntry[]) => {
  const switchGuild = vi.fn();
  renderPage(
    () => (
      <SidebarProvider>
        <GuildSidebar />
      </SidebarProvider>
    ),
    { guilds: { guilds, activeGuildId: guilds[0]?.id ?? null, switchGuild } }
  );
  return { switchGuild };
};

// The router mounts asynchronously, so the first query in each test waits.
const railButton = (name: string) => screen.findByRole("button", { name: `Switch to ${name}` });

// The flyout repeats every guild the rail shows, so queries against it are
// scoped to the panel that owns the "Guilds" heading.
const openFlyout = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Expand guild list" }));
  const heading = await screen.findByRole("heading", { name: "Guilds" });
  const header = heading.parentElement as HTMLElement;
  return { header, panel: header.parentElement as HTMLElement };
};

describe("GuildSidebar reorder mode", () => {
  it("offers a reorder action in a member guild's context menu", async () => {
    const guilds = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    setup(guilds);

    fireEvent.contextMenu(await railButton("Alpha"));

    expect(await screen.findByRole("menuitem", { name: "Reorder guilds" })).toBeInTheDocument();
  });

  it("does not offer it for a guild held through a temporary grant", async () => {
    const guilds = [
      entry({ name: "Alpha" }),
      entry({ name: "Loaner", accessType: "grant", grantExpiresAt: null }),
    ];
    setup(guilds);

    // Grant guilds only get a full row in the expanded flyout.
    const { panel } = await openFlyout();
    fireEvent.contextMenu(within(panel).getByRole("button", { name: "Switch to Loaner" }));

    expect(await screen.findByRole("menuitem", { name: "Copy guild ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reorder guilds" })).not.toBeInTheDocument();
  });

  it("does not offer it when there is only one guild to order", async () => {
    setup([entry({ name: "Alpha" })]);

    fireEvent.contextMenu(await railButton("Alpha"));

    expect(await screen.findByRole("menuitem", { name: "Copy guild ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reorder guilds" })).not.toBeInTheDocument();
  });

  it("turns taps into drags while reordering, and hands them back on Done", async () => {
    const guilds = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    const { switchGuild } = setup(guilds);

    fireEvent.contextMenu(await railButton("Alpha"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reorder guilds" }));

    const done = await screen.findByRole("button", { name: "Done" });
    fireEvent.click(screen.getByRole("button", { name: "Drag to reorder Beta" }));
    expect(switchGuild).not.toHaveBeenCalled();

    fireEvent.click(done);
    fireEvent.click(await railButton("Beta"));
    expect(switchGuild).toHaveBeenCalledWith(guilds[1].id);
  });

  it("exposes the same reorder toggle in the expanded guild list", async () => {
    const guilds = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    setup(guilds);

    const { header } = await openFlyout();

    fireEvent.click(within(header).getByRole("button", { name: "Reorder" }));

    expect(screen.getByText("Drag guilds to reorder them, then tap Done.")).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Done" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});
