import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildGuild, guildCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { GuildEntry } from "@/hooks/useGuilds";

import { GuildLayout } from "./$guildId";

// The layout is mounted directly rather than through the shipped tree: what is
// under test is what it renders for a given guild state, and reaching it in the
// real router means clearing the auth and server guards above it first.
const routeParams = { guildId: "7" };
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useParams: () => routeParams,
  useLocation: () => ({ pathname: `/c/${routeParams.guildId}` }),
  Outlet: () => <div data-testid="guild-outlet" />,
}));

const guildEntry = (id: number, name: string, extra: Partial<GuildEntry> = {}): GuildEntry =>
  ({ ...buildGuild({ id, name }), accessType: "member", ...extra }) as GuildEntry;

describe("the guild layout waits for this tab to adopt the URL's guild", () => {
  // `renderPage` rather than a bare render: the not-a-member branch draws a
  // link home, which needs a router around it.
  const show = (
    activeGuildId: number | null,
    { loading = false, guilds = [guildEntry(3, "Alpha"), guildEntry(7, "Beta")] } = {}
  ) =>
    renderPage(GuildLayout, {
      guilds: { guilds, activeGuildId, loading, syncGuildFromUrl: vi.fn() },
    });

  it("holds the subtree while the tab still points at another guild", async () => {
    // A fresh tab is seeded from storage and adopts the URL in an effect that
    // runs a render after the guild list arrives. Guild-scoped hooks below read
    // that value for their query keys, so a subtree rendered in that window
    // asks the previous guild and asks again once the adoption lands.
    show(3);
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("guild-outlet")).not.toBeInTheDocument();
  });

  it("renders the subtree once the two agree", async () => {
    show(7);
    expect(await screen.findByTestId("guild-outlet")).toBeInTheDocument();
  });

  it("holds it while the guild list is still loading", async () => {
    show(7, { loading: true });
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryByTestId("guild-outlet")).not.toBeInTheDocument();
  });

  it("still says so plainly when the URL names a guild you are not in", async () => {
    // The wait sits after the membership check, so a guild you cannot enter
    // reports that rather than spinning on an adoption that never comes.
    show(3, { guilds: [guildEntry(3, "Alpha")] });
    expect(await screen.findByText(/not a member/i)).toBeInTheDocument();
    expect(screen.queryByTestId("guild-outlet")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

describe("a suspended community is closed to its own administrators", () => {
  const show = (guild: GuildEntry, syncGuildFromUrl = vi.fn()) => {
    renderPage(GuildLayout, {
      guilds: { guilds: [guild], activeGuildId: null, loading: false, syncGuildFromUrl },
    });
    return syncGuildFromUrl;
  };

  // A suspended community as its administrator's list serves it.
  const closedToItsAdmin: Partial<GuildEntry> = {
    role: "admin",
    status: "suspended",
    can: guildCan("admin", { enter: false }),
  };

  it("shows the closed page and never adopts the community", async () => {
    const sync = show(guildEntry(7, "Beta", closedToItsAdmin));
    expect(await screen.findByText("This community is suspended")).toBeInTheDocument();
    expect(screen.queryByTestId("guild-outlet")).not.toBeInTheDocument();
    expect(sync).not.toHaveBeenCalled();
  });

  it("names who to contact when the deployment has said", async () => {
    show(
      guildEntry(7, "Beta", {
        ...closedToItsAdmin,
        contact_email: "trust@example.com",
      })
    );
    expect(await screen.findByText(/Contact trust@example\.com\./)).toBeInTheDocument();
  });

  it("says to contact whoever runs the server when nobody is named", async () => {
    show(guildEntry(7, "Beta", closedToItsAdmin));
    expect(await screen.findByText(/Contact whoever runs this server\./)).toBeInTheDocument();
  });

  it("lets a platform grant through", async () => {
    const sync = show(guildEntry(7, "Beta", { status: "suspended", accessType: "grant" }));
    await waitFor(() => expect(sync).toHaveBeenCalledWith(7));
    expect(screen.queryByText("This community is suspended")).not.toBeInTheDocument();
  });
});
