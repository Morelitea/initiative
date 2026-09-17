import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

// What this member is in this community, and what the operator has granted it.
// Flipped per test.
let guildRole = "superadmin";
let isGuildAdmin = true;
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let authOptions: string[] = ["restrictions", "providers", "require_sign_in"];

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
    authOptions = ["restrictions", "providers", "require_sign_in"];
  });

  it("offers the Authentication tab to the seat that owns it", async () => {
    render();

    expect(await screen.findByRole("tab", { name: /authentication/i })).toBeInTheDocument();
  });

  it.each(["admin", "member"])("does not offer it to %s", async (role) => {
    // Everything on that tab is the superadmin's to set, so an ordinary
    // admin is not shown a page they could only look at.
    guildRole = role;
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /authentication/i })).not.toBeInTheDocument();
  });

  it("offers only Authentication to a superadmin settings grantee", async () => {
    guildRole = "member";
    isGuildAdmin = false;
    grantSettingsLevel = "superadmin";
    // A grantee's entry carries none of the community's own options; the page
    // reads the real ones for itself.
    authOptions = [];
    render();

    expect(await screen.findByRole("tab", { name: /authentication/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /community/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/permission/i)).not.toBeInTheDocument();
  });

  it("does not offer it to a community the operator has granted nothing", async () => {
    // Which is most of them: without the master option there is nothing on
    // that tab for anybody, seat or no seat.
    authOptions = [];
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /authentication/i })).not.toBeInTheDocument();
  });
});
