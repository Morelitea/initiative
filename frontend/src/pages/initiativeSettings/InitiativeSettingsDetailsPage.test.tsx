import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildGuild, buildInitiative } from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeJoinPolicy } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { InitiativeSettingsDetailsPage } from "./InitiativeSettingsDetailsPage";

const INITIATIVE_ID = 7;

/** Records what each PATCH actually sent, so a save can be read field by field. */
function stubInitiative(joinPolicy: InitiativeJoinPolicy = "private") {
  const patches: unknown[] = [];
  server.use(
    guildHttp.get("/initiatives/", () =>
      HttpResponse.json([
        buildInitiative({ id: INITIATIVE_ID, name: "Apollo", join_policy: joinPolicy }),
      ])
    ),
    guildHttp.patch("/initiatives/:id", async ({ request }) => {
      const body = await request.json();
      patches.push(body);
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, name: "Apollo" }));
    })
  );
  return patches;
}

const renderDetails = (role: "admin" | "member" = "admin") =>
  renderPage(InitiativeSettingsDetailsPage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
    initialRoute: "/g/$guildId/i/$initiativeId/settings",
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
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
    stubInitiative("request");

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
});
