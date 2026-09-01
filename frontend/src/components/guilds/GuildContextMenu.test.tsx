/**
 * Inviting members from a guild's context menu, against the guild's seat cap.
 *
 * The cap (`max_users`) and the current headcount (`member_count`) both ride
 * on the admin's own guild payload, so the menu can tell a full guild from a
 * roomy one without asking the server first.
 *
 * What a full guild is offered depends on the deployment: self-hosted, the cap
 * is the operator's to lift; with a billing portal it comes with the plan, and
 * the item leads there instead.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";

import { GuildContextMenu } from "./GuildContextMenu";

const mintInvite = vi.hoisted(() => vi.fn());
const mintHandoff = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/guilds/guilds", () => ({
  createGuildInviteApiV1GuildsGuildIdInvitesPost: mintInvite,
  createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost: mintHandoff,
}));

// Null billing is the self-hosted deployment; a test opts into the portal.
const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));

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
  beforeEach(() => {
    state.billing = null;
    mintInvite.mockReset();
    mintHandoff.mockReset();
  });

  it("offers the invite action while a seat is free", async () => {
    setup({ max_users: 3, member_count: 2 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");
  });

  it("offers it when the community has no cap at all", async () => {
    setup({ max_users: null, member_count: 42 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");
  });

  it("disables it, and says why, once every seat is taken", async () => {
    setup({ max_users: 2, member_count: 2 });

    await openMenu();

    const item = await screen.findByRole("menuitem", { name: "Invite members (community full)" });
    expect(item).toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);
    expect(mintInvite).not.toHaveBeenCalled();
  });

  it("sends a full community to the billing portal where one is configured", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintHandoff.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const guild = setup({ id: 42, max_users: 1, member_count: 1 });

    await openMenu();
    const item = await screen.findByRole("menuitem", { name: "Upgrade to invite members" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");

    fireEvent.click(item);

    expect(mintInvite).not.toHaveBeenCalled();
    await waitFor(() => expect(mintHandoff).toHaveBeenCalledWith(guild.id));
    await waitFor(() =>
      expect(tab.location.href).toBe(
        "https://billing.example.com/upgrade?guild=42&lang=en#handoff=TOK"
      )
    );
    openSpy.mockRestore();
  });
});
