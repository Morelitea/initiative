import { cleanup, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser, guildCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type {
  CommunityAuthOption,
  CommunityBillingSummaryRead,
  CommunityRole,
} from "@/api/generated/initiativeAPI.schemas";
import type { useAppConfig as useAppConfigType } from "@/hooks/useAppConfig";
import type { useGuildBillingSummary as useGuildBillingSummaryType } from "@/hooks/useGuildBillingSummary";
import type { GuildEntry } from "@/hooks/useGuilds";

// What this member is in this community, and what the operator has granted it.
// Flipped per test.
let guildRole: CommunityRole = "superadmin";
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let reachesContent = true;
let authOptions: CommunityAuthOption[] = ["restrictions", "providers"];
// The server's answer to whether the settings may be changed; left unset, the
// factory answers the way the server does for a member.
let canWriteSettings: boolean | undefined;
// The deployment's billing portal; null on a self-hosted install.
let billing: { url: string } | null = null;

// What the billing service said of the plan; undefined is "not asked".
let summary: CommunityBillingSummaryRead | undefined;

vi.mock(import("@/hooks/useAppConfig"), async (importOriginal) => ({
  ...(await importOriginal()),
  useAppConfig: () => ({ billing }) as unknown as ReturnType<typeof useAppConfigType>,
}));
vi.mock(import("@/hooks/useGuildBillingSummary"), () => ({
  useGuildBillingSummary: () =>
    ({ data: summary }) as unknown as ReturnType<typeof useGuildBillingSummaryType>,
}));

// Partial: the render helper reaches for ``GuildContext`` from this module.
vi.mock(import("@/hooks/useGuilds"), async (importOriginal) => ({
  ...(await importOriginal()),
  useGuilds: () => {
    const activeGuild: GuildEntry = {
      ...buildGuild({
        id: 4,
        name: "Test Community",
        role: guildRole,
        auth_options: authOptions,
        can: guildCan(guildRole, {
          content: reachesContent,
          ...(canWriteSettings === undefined ? {} : { configure: canWriteSettings }),
        }),
      }),
      grantSettingsLevel,
    };
    return {
      guilds: [activeGuild],
      activeGuild,
      activeGuildId: 4,
      activeGuildReadOnly: false,
      loading: false,
      error: null,
      refreshGuilds: vi.fn(),
      switchGuild: vi.fn(),
      syncGuildFromUrl: vi.fn(),
      createGuild: vi.fn(),
      updateGuildInState: vi.fn(),
      reorderGuilds: vi.fn(),
      canCreateGuilds: false,
    };
  },
}));

import { GuildSettingsLayout } from "./GuildSettingsLayout";

const render = () => renderPage(GuildSettingsLayout, { auth: { user: buildUser() } });

describe("GuildSettingsLayout", () => {
  beforeEach(() => {
    guildRole = "superadmin";
    grantSettingsLevel = null;
    reachesContent = true;
    authOptions = ["restrictions", "providers"];
    canWriteSettings = undefined;
    billing = null;
    summary = undefined;
  });

  it("puts Usage first for the seat, and keeps it from an ordinary admin", async () => {
    // What the community uses against its caps, and on a hosted install the
    // plan they come with, is the seat's — like its sign-in.
    render();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs[0]).toHaveAccessibleName("Usage");

    cleanup();
    guildRole = "admin";
    render();
    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /usage/i })).not.toBeInTheDocument();
  });

  it("names it for the plan where there is a billing portal", async () => {
    billing = { url: "https://billing.example.com" };
    render();
    const tabs = await screen.findAllByRole("tab");
    expect(tabs[0]).toHaveAccessibleName("Plan & usage");
  });

  it("marks the tab while a trial runs", async () => {
    billing = { url: "https://billing.example.com" };
    const now = new Date();
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 3);
    const pad = (n: number) => String(n).padStart(2, "0");
    summary = {
      available: true,
      trial_ends_on: `${end.getFullYear()}-${pad(end.getMonth() + 1)}-${pad(end.getDate())}`,
      payment_failed: false,
    };
    render();
    expect(await screen.findByRole("tab", { name: /plan & usage/i })).toHaveTextContent(
      "Trial · 3 days"
    );
  });

  it("marks the tab when a payment failed", async () => {
    billing = { url: "https://billing.example.com" };
    summary = { available: true, payment_failed: true };
    render();
    const tab = await screen.findByRole("tab", { name: /plan & usage/i });
    expect(within(tab).getByRole("img", { name: "Payment failed" })).toBeInTheDocument();
  });

  it("leaves the tab plain when billing could not say", async () => {
    billing = { url: "https://billing.example.com" };
    summary = { available: false, payment_failed: false };
    render();
    const tab = await screen.findByRole("tab", { name: /plan & usage/i });
    expect(tab).toHaveAccessibleName("Plan & usage");
  });

  it("offers the Security tab to the seat that owns it", async () => {
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
  });

  it.each<[CommunityAuthOption]>([["providers"], ["restrictions"]])(
    "offers it on the %s grant alone",
    async (option) => {
      // The two grants are independent, and either one puts something on the
      // page worth reaching.
      authOptions = [option];
      render();

      expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
    }
  );

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

  it("does not offer it to an ordinary admin", async () => {
    // Everything on that tab is the superadmin's to set, so an ordinary
    // admin is not shown a page they could only look at. A member gets no
    // settings section at all — see "turns a member with nothing away".
    guildRole = "admin";
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
    grantSettingsLevel = "superadmin";
    reachesContent = false;
    render();

    expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /initiatives/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /trash/i })).not.toBeInTheDocument();
  });

  it("shows the settings for viewing when the server says they are not changed here", async () => {
    // A settings grant with no read/write grant beside it reads what its rung
    // reaches; every control on the pages is disabled, and the page says why.
    guildRole = "superadmin";
    grantSettingsLevel = "superadmin";
    canWriteSettings = false;
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.getByText(/read\/write grant/i)).toBeInTheDocument();
    expect(screen.getByRole("group")).toBeDisabled();
  });

  it("leaves the settings changeable when the server says so", async () => {
    guildRole = "superadmin";
    grantSettingsLevel = "superadmin";
    canWriteSettings = true;
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
    expect(screen.queryByText(/read\/write grant/i)).not.toBeInTheDocument();
    expect(screen.getByRole("group")).toBeEnabled();
  });

  it("turns a member with nothing away", async () => {
    guildRole = "member";
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
