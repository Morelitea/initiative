/**
 * The seat-cap notice on Settings › Users.
 *
 * A full guild mints no invite, and what the admin can do about it depends on
 * the deployment: self-hosted, the cap is the operator's to lift, so the copy
 * says to ask one. Where a billing portal exists the cap comes with the plan —
 * no operator is reachable to raise it — so the notice names the plan and
 * offers the way to change it.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { GuildRead } from "@/api/generated/initiativeAPI.schemas";

const state = vi.hoisted(() => ({ billing: null as { url: string } | null }));
vi.mock("@/hooks/useAppConfig", () => ({ useAppConfig: () => ({ billing: state.billing }) }));

const mintHandoff = vi.hoisted(() => vi.fn());
vi.mock("@/api/generated/guilds/guilds", () => ({
  createGuildInviteApiV1GuildsGuildIdInvitesPost: vi.fn(),
  deleteGuildInviteApiV1GuildsGuildIdInvitesInviteIdDelete: vi.fn(),
  listGuildInvitesApiV1GuildsGuildIdInvitesGet: vi.fn().mockResolvedValue([]),
  createGuildBillingHandoffApiV1GuildsGuildIdBillingHandoffPost: mintHandoff,
}));

vi.mock("@/hooks/useUsers", () => ({
  useUsers: () => ({ data: [], isLoading: false, isError: false }),
  useApproveUser: () => ({ mutate: vi.fn() }),
  useUpdateGuildMembership: () => ({ mutate: vi.fn() }),
  useExportGuildUsersCsv: () => ({ mutate: vi.fn() }),
}));

vi.mock("@/components/guilds/UnownedContentCard", () => ({ UnownedContentCard: () => null }));

import { SettingsUsersPage } from "./SettingsUsersPage";

const setup = (overrides: Partial<GuildRead>) => {
  const guild = buildGuild({ role: "admin", name: "Alpha", ...overrides }) as GuildRead;
  renderPage(() => <SettingsUsersPage />, {
    guilds: { guilds: [guild], activeGuildId: guild.id, activeGuild: guild },
  });
  return guild;
};

describe("SettingsUsersPage seat cap", () => {
  beforeEach(() => {
    state.billing = null;
    mintHandoff.mockReset();
  });

  it("points a self-hosted admin at the operator who can raise the cap", async () => {
    setup({ max_users: 2, member_count: 2 });

    expect(await screen.findByText(/ask a platform admin to raise the limit/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upgrade" })).not.toBeInTheDocument();
  });

  it("names the plan and offers the portal when billing is configured", async () => {
    state.billing = { url: "https://billing.example.com" };
    mintHandoff.mockResolvedValue({ handoff_token: "TOK", expires_in_seconds: 60 });
    const tab = { location: { href: "" }, opener: {} as unknown };
    const openSpy = vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const guild = setup({ id: 42, max_users: 1, member_count: 1, tier_name: "starter" });

    expect(
      await screen.findByText(/The starter plan includes a single seat, and it's taken/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/ask a platform admin/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Upgrade" }));

    await waitFor(() => expect(mintHandoff).toHaveBeenCalledWith(guild.id));
    await waitFor(() =>
      expect(tab.location.href).toBe(
        "https://billing.example.com/upgrade?guild=42&lang=en#handoff=TOK"
      )
    );
    openSpy.mockRestore();
  });

  it("falls back to plan-free wording when the guild carries no plan name", async () => {
    state.billing = { url: "https://billing.example.com" };
    setup({ max_users: 5, member_count: 5, tier_name: null });

    expect(await screen.findByText(/All 5 seats on your plan are in use/i)).toBeInTheDocument();
  });

  it("says nothing about seats while one is free", async () => {
    setup({ max_users: 5, member_count: 2 });

    await screen.findByRole("button", { name: "Generate invite" });
    expect(screen.queryByText(/seats/i)).not.toBeInTheDocument();
  });
});
