import { cleanup, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

// What this member is in this community, and what the operator has granted it.
// Flipped per test.
let guildRole = "superadmin";
let isGuildAdmin = true;
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let reachesContent = true;
let authOptions: string[] = ["restrictions", "providers"];

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({
    activeGuild: {
      id: 4,
      name: "Test Community",
      role: guildRole,
      is_admin: isGuildAdmin,
      grantSettingsLevel,
      reachesContent,
      auth_options: authOptions,
    },
    activeGuildId: 4,
  }),
}));

import { GuildSettingsLayout } from "./GuildSettingsLayout";

const render = () => renderPage(GuildSettingsLayout, { auth: { user: buildUser() } });

describe("GuildSettingsLayout", () => {
  beforeEach(() => {
    guildRole = "superadmin";
    isGuildAdmin = true;
    grantSettingsLevel = null;
    reachesContent = true;
    authOptions = ["restrictions", "providers"];
  });

  it("offers the Security tab to the seat that owns it", async () => {
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
  });

  it.each([["providers"], ["restrictions"]])("offers it on the %s grant alone", async (option) => {
    // The two grants are independent, and either one puts something on the
    // page worth reaching.
    authOptions = [option];
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
  });

  it("offers Integrations to the seat and not to an admin", async () => {
    // What the community hands to somebody outside it is the seat's, the way
    // its sign-in is.
    render();
    expect(await screen.findByRole("tab", { name: /integrations/i })).toBeInTheDocument();

    cleanup();
    guildRole = "admin";
    render();
    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /integrations/i })).not.toBeInTheDocument();
  });

  it("offers Data to the seat and not to an admin", async () => {
    // Taking the community out in one file, or putting one back, reaches as
    // far as deleting it does — so it sits with the same seat.
    render();
    expect(await screen.findByRole("tab", { name: /data/i })).toBeInTheDocument();

    cleanup();
    guildRole = "admin";
    render();
    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /data/i })).not.toBeInTheDocument();
  });

  it.each(["admin", "member"])("does not offer it to %s", async (role) => {
    // Everything on that tab is the superadmin's to set, so an ordinary
    // admin is not shown a page they could only look at.
    guildRole = role;
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /security/i })).not.toBeInTheDocument();
  });

  it("gives a superadmin settings grantee every tab the seat holds", async () => {
    // The rung is "what the seat holds", and the seat sits above admin — so
    // the community's own configuration comes with it, Data and the danger
    // zone included. The entry carries the rung the server recorded on the
    // grant, which is what the seat is read from.
    guildRole = "superadmin";
    isGuildAdmin = true;
    grantSettingsLevel = "superadmin";
    // A grantee's entry carries none of the community's own options; the page
    // reads the real ones for itself.
    authOptions = [];
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /integrations/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /users/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /data/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /danger/i })).toBeInTheDocument();
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument();
  });

  it("gives an admin settings grantee what an admin administers, and no more", async () => {
    guildRole = "admin";
    isGuildAdmin = true;
    grantSettingsLevel = "admin";
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /users/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /security/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /integrations/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument();
  });

  it("drops the content-backed tabs from a settings-only grant", async () => {
    // Initiatives and Trash are built on routes the server refuses to a grant
    // carrying no content level, so they are not offered.
    guildRole = "superadmin";
    isGuildAdmin = true;
    grantSettingsLevel = "superadmin";
    reachesContent = false;
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /initiatives/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /trash/i })).not.toBeInTheDocument();
  });

  it("turns a member with nothing away", async () => {
    guildRole = "member";
    isGuildAdmin = false;
    render();

    expect(await screen.findByText(/permission/i)).toBeInTheDocument();
  });

  it("does not offer it to a community the operator has granted nothing", async () => {
    // Which is most of them: with neither grant there is nothing on that tab
    // for anybody, seat or no seat.
    authOptions = [];
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /security/i })).not.toBeInTheDocument();
  });
});
