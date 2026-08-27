/**
 * Inviting members from a guild's context menu, against the guild's seat cap.
 *
 * The cap (`max_users`) and the current headcount (`member_count`) both ride
 * on the admin's own guild payload, so the menu can tell a full guild from a
 * roomy one without asking the server first.
 */
import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";

import { GuildContextMenu } from "./GuildContextMenu";

const mintInvite = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/guilds/guilds", () => ({
  createGuildInviteApiV1GuildsGuildIdInvitesPost: mintInvite,
}));

const setup = (overrides: Partial<GuildRead>) => {
  const guild = buildGuild({ role: "admin", name: "Alpha", ...overrides }) as GuildRead;
  renderPage(
    () => (
      <GuildContextMenu guild={guild}>
        <button type="button">Alpha</button>
      </GuildContextMenu>
    ),
    { guilds: { guilds: [], activeGuildId: guild.id } }
  );
  return guild;
};

const openMenu = async () => {
  fireEvent.contextMenu(await screen.findByRole("button", { name: "Alpha" }));
};

describe("GuildContextMenu invite action", () => {
  it("offers the invite action while a seat is free", async () => {
    setup({ max_users: 3, member_count: 2 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");
  });

  it("offers it when the guild has no cap at all", async () => {
    setup({ max_users: null, member_count: 42 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");
  });

  it("disables it, and says why, once every seat is taken", async () => {
    setup({ max_users: 2, member_count: 2 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members (guild full)" });
    expect(item).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);
    expect(mintInvite).not.toHaveBeenCalled();
  });
});
