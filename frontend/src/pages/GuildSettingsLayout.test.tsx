import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

// What this member is in this community. Flipped per test.
let guildRole = "superadmin";

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => ({
    activeGuild: {
      id: 4,
      name: "Test Community",
      role: guildRole,
      is_admin: true,
      auth_options: ["providers", "require_sign_in"],
    },
    activeGuildId: 4,
  }),
}));

import { GuildSettingsLayout } from "./GuildSettingsLayout";

const render = () => renderPage(GuildSettingsLayout, { auth: { user: buildUser() } });

describe("GuildSettingsLayout", () => {
  beforeEach(() => {
    guildRole = "superadmin";
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
});
