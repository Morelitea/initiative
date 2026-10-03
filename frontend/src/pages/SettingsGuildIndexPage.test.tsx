import { waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser, guildCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityRole } from "@/api/generated/initiativeAPI.schemas";
import type { useAppConfig as useAppConfigType } from "@/hooks/useAppConfig";
import type { GuildEntry } from "@/hooks/useGuilds";

let guildRole: CommunityRole = "superadmin";
let billing: { url: string } | null = null;

vi.mock(import("@/hooks/useAppConfig"), async (importOriginal) => ({
  ...(await importOriginal()),
  useAppConfig: () => ({ billing }) as unknown as ReturnType<typeof useAppConfigType>,
}));

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => {
    const activeGuild: GuildEntry = buildGuild({
      id: 4,
      role: guildRole,
      can: guildCan(guildRole),
    });
    return {
      guilds: [activeGuild],
      activeGuild,
      activeGuildId: 4,
    } as unknown as ReturnType<typeof import("@/hooks/useGuilds").useGuilds>;
  },
}));

import { SettingsGuildIndexPage } from "./SettingsGuildIndexPage";

const landing = async () => {
  const { router } = renderPage(SettingsGuildIndexPage, {
    auth: { user: buildUser() },
    initialRoute: "/c/$guildId/settings",
    routeParams: { guildId: "4" },
  });
  await waitFor(() => expect(router.state.location.pathname).not.toBe("/c/4/settings"));
  return router.state.location.pathname;
};

// `/settings` names no tab, so it opens the first one this person may open —
// never one that would turn them away.
describe("SettingsGuildIndexPage", () => {
  beforeEach(() => {
    guildRole = "superadmin";
    billing = null;
  });

  it("lands the seat on Usage", async () => {
    expect(await landing()).toBe("/c/4/settings/usage");
  });

  it("lands the seat of a hosted install on Usage too", async () => {
    billing = { url: "https://billing.example.com" };
    expect(await landing()).toBe("/c/4/settings/usage");
  });

  it("lands an ordinary admin, who cannot open Usage, on Community", async () => {
    guildRole = "admin";
    expect(await landing()).toBe("/c/4/settings/community");
  });
});
