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

import { InitiativeSettingsPage } from "./InitiativeSettingsPage";

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
    guildHttp.get("/initiatives/:id/roles", () => HttpResponse.json([])),
    guildHttp.patch("/initiatives/:id", async ({ request }) => {
      const body = await request.json();
      patches.push(body);
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, name: "Apollo" }));
    })
  );
  return patches;
}

const renderSettings = () =>
  renderPage(InitiativeSettingsPage, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) },
    initialRoute: "/g/$guildId/i/$initiativeId/settings",
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
  });

describe("InitiativeSettingsPage join policy", () => {
  it("offers only the two policies this release can deliver", async () => {
    stubInitiative();

    renderSettings();

    expect(await screen.findByRole("radio", { name: /Invite only/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Anyone can join/ })).toBeInTheDocument();
    // Knocking arrives with the request flow; offering it now would promise a
    // queue nobody can approve from.
    expect(screen.queryByRole("radio", { name: /By request/ })).not.toBeInTheDocument();
  });

  it("saves the chosen policy on its own, touching no other field", async () => {
    const patches = stubInitiative();

    renderSettings();

    await userEvent.click(await screen.findByRole("radio", { name: /Anyone can join/ }));

    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({ join_policy: "open" });
  });

  it("keeps a policy it cannot offer rather than silently downgrading it", async () => {
    stubInitiative("request");

    renderSettings();

    // The initiative is already `request`, so the option is shown — selected —
    // instead of the screen quietly resetting it to one of its own two.
    const requestOption = await screen.findByRole("radio", { name: /By request/ });
    expect(requestOption).toBeChecked();
  });
});
