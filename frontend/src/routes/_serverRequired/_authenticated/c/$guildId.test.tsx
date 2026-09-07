import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { GuildEntry } from "@/hooks/useGuilds";

import { GuildLayout, shouldPinSuspendedGuildToSettings } from "./$guildId";

// The layout is mounted directly rather than through the shipped tree: what is
// under test is what it renders for a given guild state, and reaching it in the
// real router means clearing the auth and server guards above it first.
const routeParams = { guildId: "7" };
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useParams: () => routeParams,
  useLocation: () => ({ pathname: `/c/${routeParams.guildId}` }),
  Outlet: () => <div data-testid="guild-outlet" />,
  Navigate: ({ to }: { to: string }) => <div data-testid="navigated-to">{to}</div>,
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

describe("shouldPinSuspendedGuildToSettings", () => {
  const guildId = 5;

  it("pins content pages of the suspended guild to settings", () => {
    expect(shouldPinSuspendedGuildToSettings("/c/5", guildId)).toBe(true);
    expect(shouldPinSuspendedGuildToSettings("/c/5/", guildId)).toBe(true);
    expect(shouldPinSuspendedGuildToSettings("/c/5/tasks", guildId)).toBe(true);
    expect(shouldPinSuspendedGuildToSettings("/c/5/documents/12", guildId)).toBe(true);
  });

  it("does not redirect the settings surface itself", () => {
    expect(shouldPinSuspendedGuildToSettings("/c/5/settings", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/c/5/settings/danger-zone", guildId)).toBe(false);
  });

  it("lets pending navigations OUT of the guild through (no redirect trap)", () => {
    // The router publishes the pending target location while the suspended
    // guild's layout is still mounted — these must not bounce back to settings.
    expect(shouldPinSuspendedGuildToSettings("/", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/my-tools", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/profile", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/c/6/", guildId)).toBe(false);
    expect(shouldPinSuspendedGuildToSettings("/c/6/settings", guildId)).toBe(false);
  });

  it("does not treat a prefix-overlapping guild id as this guild", () => {
    expect(shouldPinSuspendedGuildToSettings("/c/55/tasks", guildId)).toBe(false);
  });

  it("does not exempt a prefix-overlapping settings sibling route", () => {
    expect(shouldPinSuspendedGuildToSettings("/c/5/settings-admin", guildId)).toBe(true);
  });
});
