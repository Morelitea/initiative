import { cleanup, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildGuild, buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { GuildAuthOption, GuildRole } from "@/api/generated/initiativeAPI.schemas";
import type { GuildEntry } from "@/hooks/useGuilds";

// What this member is in this community, and what the operator has granted it.
// Flipped per test.
let guildRole: GuildRole = "superadmin";
let grantSettingsLevel: "admin" | "superadmin" | null = null;
let reachesContent = true;
let authOptions: GuildAuthOption[] = ["restrictions", "providers"];
// The server's answer to whether the settings may be changed; left unset, the
// factory answers the way the server does for a member.
let canWriteSettings: boolean | undefined;

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
        ...(canWriteSettings === undefined ? {} : { can_write_settings: canWriteSettings }),
      }),
      grantSettingsLevel,
      reachesContent,
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
  });

  it("offers the Security tab to the seat that owns it", async () => {
    render();

    expect(await screen.findByRole("tab", { name: /security/i })).toBeInTheDocument();
  });

  it.each<[GuildAuthOption]>([["providers"], ["restrictions"]])(
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

  describe("the Intake tab", () => {
    // Whether this community receives the deployment's operations work is the
    // server's answer: its intake read succeeds there and is 404 everywhere
    // else.
    const intakeAnswers = (status: 200 | 404) => {
      const seen = vi.fn();
      server.use(
        http.get("/api/v1/g/4/intake", () => {
          seen();
          return status === 200
            ? HttpResponse.json({ bindings: [] })
            : HttpResponse.json({ detail: "INTAKE_NOT_OPERATIONS_GUILD" }, { status: 404 });
        })
      );
      return seen;
    };

    it("is offered to the seat of the operations community", async () => {
      intakeAnswers(200);
      render();

      expect(await screen.findByRole("tab", { name: /intake/i })).toBeInTheDocument();
    });

    it("is not offered to the seat of any other community", async () => {
      const seen = intakeAnswers(404);
      render();

      expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
      await vi.waitFor(() => expect(seen).toHaveBeenCalled());
      expect(screen.queryByRole("tab", { name: /intake/i })).not.toBeInTheDocument();
    });

    it("is not offered, or asked about, for an admin who is not the seat", async () => {
      const seen = intakeAnswers(200);
      guildRole = "admin";
      render();

      expect(await screen.findByRole("tab", { name: /community/i })).toBeInTheDocument();
      expect(screen.queryByRole("tab", { name: /intake/i })).not.toBeInTheDocument();
      expect(seen).not.toHaveBeenCalled();
    });
  });
});
