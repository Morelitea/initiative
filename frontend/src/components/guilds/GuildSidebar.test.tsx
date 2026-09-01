/**
 * Reordering guilds on a touch screen.
 *
 * Touch has one press-and-hold, and the context menu owns it. Wiring a drag
 * sensor to the same gesture meant a long press on a guild started a reorder
 * instead of opening the menu, so the menu was unreachable on a phone. Touch
 * dragging now waits behind an explicit "Reorder communities" action, and while it
 * is on a tap moves the guild rather than switching to it.
 *
 * A guild reached through a temporary access grant is not part of the user's
 * order, so it offers no reorder action.
 */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import { SidebarProvider } from "@/components/ui/sidebar";
import type { GuildEntry } from "@/hooks/useGuilds";

import { GuildSidebar } from "./GuildSidebar";

// Deployment config, mocked so a test can put the sidebar in whichever shape it
// is about: no billing portal (self-hosted) or one configured, and a community
// directory the platform owner is running or has switched off.
const state = vi.hoisted(() => ({
  billing: null as { url: string } | null,
  communityDirectory: true,
}));
const mintMock = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/useAppConfig", () => ({
  useAppConfig: () => ({
    billing: state.billing,
    communityDirectoryEnabled: state.communityDirectory,
  }),
}));
vi.mock("@/api/generated/guilds/guilds", async () => {
  const actual = await vi.importActual<typeof import("@/api/generated/guilds/guilds")>(
    "@/api/generated/guilds/guilds"
  );
  return { ...actual, createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost: mintMock };
});
vi.mock("@/lib/chesterToast", () => ({
  toast: { info: vi.fn(), error: vi.fn(), success: vi.fn() },
}));

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
// scoped to the panel that owns the "Communities" heading.
const openFlyout = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Expand community list" }));
  const heading = await screen.findByRole("heading", { name: "Communities" });
  const header = heading.parentElement as HTMLElement;
  return { header, panel: header.parentElement as HTMLElement };
};

describe("GuildSidebar reorder mode", () => {
  it("offers a reorder action in a member community's context menu", async () => {
    const guilds = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    setup(guilds);

    fireEvent.contextMenu(await railButton("Alpha"));

    expect(
      await screen.findByRole("menuitem", { name: "Reorder communities" })
    ).toBeInTheDocument();
  });

  it("does not offer it for a community held through a temporary grant", async () => {
    const guilds = [
      entry({ name: "Alpha" }),
      entry({ name: "Loaner", accessType: "grant", grantExpiresAt: null }),
    ];
    setup(guilds);

    // Grant guilds only get a full row in the expanded flyout.
    const { panel } = await openFlyout();
    fireEvent.contextMenu(within(panel).getByRole("button", { name: "Switch to Loaner" }));

    expect(await screen.findByRole("menuitem", { name: "Copy community ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reorder communities" })).not.toBeInTheDocument();
  });

  it("does not offer it when there is only one community to order", async () => {
    setup([entry({ name: "Alpha" })]);

    fireEvent.contextMenu(await railButton("Alpha"));

    expect(await screen.findByRole("menuitem", { name: "Copy community ID" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Reorder communities" })).not.toBeInTheDocument();
  });

  it("turns taps into drags while reordering, and hands them back on Done", async () => {
    const guilds = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    const { switchGuild } = setup(guilds);

    fireEvent.contextMenu(await railButton("Alpha"));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Reorder communities" }));

    const done = await screen.findByRole("button", { name: "Done" });
    fireEvent.click(screen.getByRole("button", { name: "Drag to reorder Beta" }));
    expect(switchGuild).not.toHaveBeenCalled();

    fireEvent.click(done);
    fireEvent.click(await railButton("Beta"));
    expect(switchGuild).toHaveBeenCalledWith(guilds[1].id);
  });

  it("exposes the same reorder toggle in the expanded community list", async () => {
    const guilds = [entry({ name: "Alpha" }), entry({ name: "Beta" })];
    setup(guilds);

    const { header } = await openFlyout();

    fireEvent.click(within(header).getByRole("button", { name: "Reorder" }));

    expect(
      screen.getByText("Drag communities to reorder them, then tap Done.")
    ).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Done" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});

/**
 * Creating a guild on a deployment that has a billing portal.
 *
 * A new guild starts on the deployment's default plan, so the flow hands the
 * creator straight to the portal to see that plan and add payment details.
 * With no portal configured (the self-hosted default) creation just finishes.
 */
describe("GuildSidebar community creation", () => {
  const createNamedGuild = async (createGuild: ReturnType<typeof vi.fn>) => {
    renderPage(
      () => (
        <SidebarProvider>
          <GuildSidebar />
        </SidebarProvider>
      ),
      { guilds: { guilds: [entry({ name: "Alpha" })], activeGuildId: 1, createGuild } }
    );
    fireEvent.click(await screen.findByRole("button", { name: "Create Community" }));
    fireEvent.change(await screen.findByLabelText("Community name"), {
      target: { value: "Beta" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create community" }));
  };

  beforeEach(() => {
    state.billing = null;
    mintMock.mockReset();
  });

  it("sends the creator to the portal with the minted token in the fragment", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintMock.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const createGuild = vi.fn().mockResolvedValue(buildGuild({ id: 42, name: "Beta" }));
    const tab = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    await createNamedGuild(createGuild);

    await waitFor(() => expect(mintMock).toHaveBeenCalledWith(42));
    await waitFor(() =>
      expect(tab.location.href).toBe(
        "https://billing.example.com/upgrade?guild=42&lang=en#handoff=TOK"
      )
    );
    openSpy.mockRestore();
  });

  it("opens nothing when the deployment has no billing portal", async () => {
    const createGuild = vi.fn().mockResolvedValue(buildGuild({ id: 42, name: "Beta" }));
    const openSpy = vi.spyOn(window, "open");

    await createNamedGuild(createGuild);

    await waitFor(() => expect(createGuild).toHaveBeenCalled());
    expect(openSpy).not.toHaveBeenCalled();
    expect(mintMock).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("closes the reserved tab when creation fails", async () => {
    state.billing = { url: "https://billing.example.com" };
    const createGuild = vi.fn().mockRejectedValue(new Error("nope"));
    const tab = { location: { href: "" }, opener: {} as unknown, close: vi.fn() };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);

    await createNamedGuild(createGuild);

    await waitFor(() => expect(tab.close).toHaveBeenCalled());
    expect(mintMock).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});

describe("the way into the community directory", () => {
  beforeEach(() => {
    state.communityDirectory = true;
  });

  it("sits in the rail under the add-a-community button", async () => {
    setup([entry({ id: 1, name: "Alpha" })]);

    const link = await screen.findByRole("link", { name: "Join a community" });
    expect(link).toHaveAttribute("href", "/communities");
  });

  it("is offered even where communities cannot be created", async () => {
    // A deployment with guild creation switched off is exactly where joining an
    // existing guild is the only way into one.
    renderPage(
      () => (
        <SidebarProvider>
          <GuildSidebar />
        </SidebarProvider>
      ),
      { guilds: { guilds: [entry({ id: 1, name: "Alpha" })], canCreateGuilds: false } }
    );

    expect(await screen.findByRole("link", { name: "Join a community" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create community" })).not.toBeInTheDocument();
  });

  it("is repeated in the expanded community list", async () => {
    setup([entry({ id: 1, name: "Alpha" })]);
    const { panel } = await openFlyout();

    expect(within(panel).getByRole("link", { name: "Join a community" })).toBeInTheDocument();
  });

  it("is absent where the platform owner runs no directory", async () => {
    state.communityDirectory = false;
    setup([entry({ id: 1, name: "Alpha" })]);
    const { panel } = await openFlyout();

    expect(screen.queryByRole("link", { name: "Join a community" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "Join a community" })).not.toBeInTheDocument();
  });
});
