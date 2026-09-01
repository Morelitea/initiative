import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  buildGuild,
  buildInitiative,
  buildInitiativeMember,
  buildUser,
  buildUserPublic,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeRead } from "@/api/generated/initiativeAPI.schemas";

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
});
