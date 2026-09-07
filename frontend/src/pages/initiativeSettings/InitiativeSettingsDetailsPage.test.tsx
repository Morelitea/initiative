import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildGuild,
  buildInitiative,
  buildInitiativeMember,
  buildInitiativeRole,
  buildUser,
  buildUserPublic,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeRead, InitiativeRoleRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { toast } from "@/lib/chesterToast";

import { InitiativeSettingsDetailsPage } from "./InitiativeSettingsDetailsPage";

const INITIATIVE_ID = 7;
const MANAGER_ID = 42;

/** The auto-join switch, when the reader is offered one at all. */
const AUTO_JOIN_LABEL = "Add every new community member automatically";
const autoJoinSwitch = () => screen.queryByLabelText(AUTO_JOIN_LABEL);

/** Records what each PATCH actually sent, so a save can be read field by field. */
function stubInitiative(overrides: Partial<InitiativeRead> = {}, patchFails?: [number, string]) {
  const patches: unknown[] = [];
  server.use(
    guildHttp.get("/initiatives/:id", () =>
      HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, name: "Apollo", ...overrides }))
    ),
    guildHttp.patch("/initiatives/:id", async ({ request }) => {
      const body = await request.json();
      patches.push(body);
      if (patchFails) {
        const [status, detail] = patchFails;
        return HttpResponse.json({ detail }, { status });
      }
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, name: "Apollo" }));
    })
  );
  return patches;
}

/** The initiative's roles, plus a record of every role PATCH the page sends. */
function stubRoles(roles: InitiativeRoleRead[]) {
  const patches: { roleId: string; body: unknown }[] = [];
  server.use(
    guildHttp.get("/initiatives/:id/roles", () => HttpResponse.json(roles)),
    guildHttp.patch("/initiatives/:id/roles/:roleId", async ({ request, params }) => {
      patches.push({ roleId: String(params.roleId), body: await request.json() });
      return HttpResponse.json(roles[0]);
    })
  );
  return patches;
}

/** The two roles most initiatives have: a manager who sees everything and an
 *  ordinary member who sees only what its permissions say. */
const managerRole = () =>
  buildInitiativeRole({
    id: 1,
    name: "project_manager",
    display_name: "Project Manager",
    is_builtin: true,
    is_manager: true,
  });
const memberRole = (permissions: Record<string, boolean> = {}) =>
  buildInitiativeRole({
    id: 2,
    name: "member",
    display_name: "Member",
    is_builtin: true,
    permissions: permissions as InitiativeRoleRead["permissions"],
  });

/** A membership that makes the signed-in user a manager of the initiative —
 *  the standing that reaches these settings without being a guild admin. */
const managerMembership = () =>
  buildInitiativeMember({ user: buildUserPublic({ id: MANAGER_ID }), is_manager: true });

const renderDetails = (role: "admin" | "member" = "admin") =>
  renderPage(InitiativeSettingsDetailsPage, {
    auth: { user: buildUser({ id: MANAGER_ID }) },
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
    initialRoute: "/c/$guildId/i/$initiativeId/settings",
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
  });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InitiativeSettingsDetailsPage", () => {
  it("offers every way into an initiative", async () => {
    stubInitiative();

    renderDetails();

    expect(await screen.findByRole("radio", { name: /Invite only/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /By request/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Anyone can join/ })).toBeInTheDocument();
  });

  it("saves the chosen policy on its own, touching no other field", async () => {
    const patches = stubInitiative();

    renderDetails();

    await userEvent.click(await screen.findByRole("radio", { name: /Anyone can join/ }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ join_policy: "open" });
  });

  it("saves the by-request policy", async () => {
    const patches = stubInitiative();

    renderDetails();

    await userEvent.click(await screen.findByRole("radio", { name: /By request/ }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ join_policy: "request" });
  });

  it("shows the initiative's current policy as the chosen one", async () => {
    stubInitiative({ join_policy: "request" });

    renderDetails();

    expect(await screen.findByRole("radio", { name: /By request/ })).toBeChecked();
  });

  it("refuses the section to someone who reached the address without the standing", async () => {
    stubInitiative();

    // Straight to the section, with no layout in front of it.
    renderDetails("member");

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /Invite only/ })).not.toBeInTheDocument();
  });

  /**
   * Auto-join enrols every future guild member on arrival. It is a guild
   * admin's decision, and the server holds it to a single pair — auto-join with
   * "anyone can join" — so the interesting cases are all about who is offered
   * it, and about never assembling a combination the server would refuse.
   */
  describe("auto-join", () => {
    it("offers the switch to a community admin on an open initiative", async () => {
      stubInitiative({ join_policy: "open" });

      renderDetails();

      expect(await screen.findByLabelText(AUTO_JOIN_LABEL)).toBeEnabled();
    });

    it("says people already in the community are not swept in", async () => {
      stubInitiative({ join_policy: "open" });

      renderDetails();

      expect(
        await screen.findByText(/People already in the community are not added/)
      ).toBeVisible();
    });

    it("will not let a closed initiative enrol anyone, and says why", async () => {
      stubInitiative({ join_policy: "private" });

      renderDetails();

      await screen.findByRole("radio", { name: /Invite only/ });
      expect(autoJoinSwitch()).toBeDisabled();
      expect(screen.getByText(/needs the “Anyone can join” policy/)).toBeVisible();
    });

    it("will not let a by-request initiative enrol anyone either", async () => {
      stubInitiative({ join_policy: "request" });

      renderDetails();

      await screen.findByRole("radio", { name: /By request/ });
      expect(autoJoinSwitch()).toBeDisabled();
    });

    it("is not offered to a manager who is not a community admin", async () => {
      stubInitiative({ join_policy: "open", members: [managerMembership()] });

      // A manager reaches these settings and may set the policy — but the
      // server refuses `auto_join` from them, so the switch is simply absent.
      renderDetails("member");

      expect(await screen.findByRole("radio", { name: /Anyone can join/ })).toBeInTheDocument();
      expect(autoJoinSwitch()).not.toBeInTheDocument();
    });

    it("saves the switch on its own, touching no other field", async () => {
      const patches = stubInitiative({ join_policy: "open" });

      renderDetails();

      await userEvent.click(await screen.findByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toEqual({ auto_join: true });
    });

    it("turns it back off", async () => {
      const patches = stubInitiative({ join_policy: "open", auto_join: true });

      renderDetails();

      expect(await screen.findByLabelText(AUTO_JOIN_LABEL)).toBeChecked();
      await userEvent.click(screen.getByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toEqual({ auto_join: false });
    });

    it("closing the initiative clears auto-join in the same save", async () => {
      const patches = stubInitiative({ join_policy: "open", auto_join: true });

      renderDetails();

      await userEvent.click(await screen.findByRole("radio", { name: /Invite only/ }));

      // Sent as one request rather than a policy change the server would refuse.
      await waitFor(() => expect(patches).toHaveLength(1));
      expect(patches[0]).toEqual({ join_policy: "private", auto_join: false });
      await waitFor(() =>
        expect(toast.info).toHaveBeenCalledWith(
          "Auto-join is off — it is only available while anyone can join."
        )
      );
    });

    it("locks the closed policies for a manager who cannot clear auto-join", async () => {
      stubInitiative({ join_policy: "open", auto_join: true, members: [managerMembership()] });

      renderDetails("member");

      expect(await screen.findByRole("radio", { name: /Anyone can join/ })).toBeEnabled();
      expect(screen.getByRole("radio", { name: /Invite only/ })).toBeDisabled();
      expect(screen.getByRole("radio", { name: /By request/ })).toBeDisabled();
      expect(screen.getByText(/Ask an admin to turn auto-join off/)).toBeVisible();
    });

    it("reports the server's refusal of a non-admin in the server's words", async () => {
      stubInitiative({ join_policy: "open" }, [403, "INITIATIVE_AUTO_JOIN_ADMIN_ONLY"]);

      renderDetails();

      await userEvent.click(await screen.findByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith("Only community admins can change auto-join")
      );
    });

    it("reports the server's refusal of a closed initiative", async () => {
      stubInitiative({ join_policy: "open" }, [400, "INITIATIVE_AUTO_JOIN_REQUIRES_OPEN"]);

      renderDetails();

      await userEvent.click(await screen.findByLabelText(AUTO_JOIN_LABEL));

      await waitFor(() =>
        expect(toast.error).toHaveBeenCalledWith(
          "Auto-join is only available for initiatives anyone can join"
        )
      );
    });
  });
  /**
   * The master switch is half of what it looks like: the initiative offering a
   * tool and a role being allowed to see it are separate gates, and the switch
   * only ever moved the first. These cover the second being asked about,
   * answered, and reported.
   */
  describe("tool switches", () => {
    it("asks who a tool is for instead of turning it straight on", async () => {
      const patches = stubInitiative();
      stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(await screen.findByLabelText("Posts"));

      expect(await screen.findByRole("dialog")).toHaveTextContent("Turn on Posts");
      // Nothing is saved until the audience question is answered.
      expect(patches).toHaveLength(0);
    });

    it("grants the tool to every ordinary role when it is for everyone", async () => {
      const initiativePatches = stubInitiative();
      const rolePatches = stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(await screen.findByLabelText("Posts"));
      await userEvent.click(await screen.findByRole("radio", { name: /Everyone in this/ }));
      await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));

      await waitFor(() => expect(initiativePatches).toEqual([{ posts_enabled: true }]));
      await waitFor(() => expect(rolePatches).toHaveLength(1));
      // The member role, not the manager one — a manager already sees everything.
      expect(rolePatches[0].roleId).toBe("2");
      expect(
        (rolePatches[0].body as { permissions: Record<string, boolean> }).permissions.posts_enabled
      ).toBe(true);
      // Reading a board and adding to it stay separate decisions.
      expect(
        (rolePatches[0].body as { permissions: Record<string, boolean> }).permissions.create_posts
      ).toBe(false);
    });

    it("leaves every role alone when the tool is for managers only", async () => {
      const initiativePatches = stubInitiative();
      const rolePatches = stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(await screen.findByLabelText("Posts"));
      await userEvent.click(await screen.findByRole("radio", { name: /Managers only/ }));
      await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));

      await waitFor(() => expect(initiativePatches).toEqual([{ posts_enabled: true }]));
      expect(rolePatches).toHaveLength(0);
    });

    it("says who can see a tool that is already on", async () => {
      stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole({ posts_enabled: true })]);

      renderDetails();

      expect(await screen.findByText(/Visible to Member/)).toBeInTheDocument();
    });

    it("warns when a tool is on but no ordinary role has been given it", async () => {
      stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole()]);

      renderDetails();

      expect(await screen.findByText(/Only managers can see this/)).toBeInTheDocument();
    });

    it("grants it to everyone from that warning, without touching the switch", async () => {
      const initiativePatches = stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      const rolePatches = stubRoles([managerRole(), memberRole()]);

      renderDetails();

      await userEvent.click(
        (await screen.findAllByRole("button", { name: "Give it to everyone" }))[0]
      );

      await waitFor(() => expect(rolePatches).toHaveLength(1));
      expect(rolePatches[0].roleId).toBe("2");
      expect(initiativePatches).toHaveLength(0);
    });

    it("says what turning a tool off hides before it hides it", async () => {
      const patches = stubInitiative({ posts_enabled: true } as Partial<InitiativeRead>);
      stubRoles([managerRole(), memberRole({ posts_enabled: true })]);

      renderDetails();

      await userEvent.click(await screen.findByLabelText("Posts"));

      expect(await screen.findByRole("alertdialog")).toHaveTextContent(
        /hides Posts and everything in it from everyone/
      );
      expect(patches).toHaveLength(0);

      await userEvent.click(screen.getByRole("button", { name: "Turn it off" }));
      await waitFor(() => expect(patches).toEqual([{ posts_enabled: false }]));
    });
  });
});
