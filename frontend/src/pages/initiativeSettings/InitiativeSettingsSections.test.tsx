/**
 * Each settings section is its own route, so each one is asked to render on its
 * own — with nothing in front of it — and to refuse a reader who arrives at the
 * address without the standing the section needs.
 */

import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildGuild,
  buildInitiative,
  buildInitiativeJoinRequest,
  buildUserSummary,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { InitiativeSettingsDangerPage } from "./InitiativeSettingsDangerPage";
import { InitiativeSettingsExportPage } from "./InitiativeSettingsExportPage";
import { InitiativeSettingsMembersPage } from "./InitiativeSettingsMembersPage";
import { InitiativeSettingsPropertiesPage } from "./InitiativeSettingsPropertiesPage";
import { InitiativeSettingsRolesPage } from "./InitiativeSettingsRolesPage";

const INITIATIVE_ID = 7;

function stubInitiative() {
  server.use(
    guildHttp.get("/initiatives/", () =>
      HttpResponse.json([buildInitiative({ id: INITIATIVE_ID, name: "Apollo" })])
    ),
    guildHttp.get("/initiatives/:id/roles", () => HttpResponse.json([]))
  );
}

const renderSection = (
  Section: React.ComponentType,
  path: string,
  role: "admin" | "member" = "admin"
) =>
  renderPage(Section, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
    initialRoute: `/c/$guildId/i/$initiativeId/settings/${path}`,
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
  });

describe("initiative settings sections", () => {
  it("serves the roster, and the queue feeding it, at /settings/members", async () => {
    stubInitiative();
    server.use(
      guildHttp.get("/initiatives/:id/join-requests", () =>
        HttpResponse.json([
          buildInitiativeJoinRequest({
            id: 11,
            initiative_id: INITIATIVE_ID,
            user: buildUserSummary({ id: 42, full_name: "Ada Lovelace" }),
          }),
        ])
      )
    );

    renderSection(InitiativeSettingsMembersPage, "members");

    expect(await screen.findByText("Requests to join")).toBeInTheDocument();
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Members")).toBeInTheDocument();
  });

  it("serves role permissions at /settings/roles", async () => {
    stubInitiative();

    renderSection(InitiativeSettingsRolesPage, "roles");

    expect(await screen.findByText("Role permissions")).toBeInTheDocument();
  });

  it("serves custom properties at /settings/properties", async () => {
    stubInitiative();
    server.use(guildHttp.get("/property-definitions/", () => HttpResponse.json([])));

    renderSection(InitiativeSettingsPropertiesPage, "properties");

    expect(await screen.findByText("Custom properties")).toBeInTheDocument();
  });

  it("serves the export wizard at /settings/export", async () => {
    stubInitiative();

    renderSection(InitiativeSettingsExportPage, "export");

    expect(await screen.findByRole("button", { name: /Export/ })).toBeInTheDocument();
  });

  it("serves archiving and deletion at /settings/danger", async () => {
    stubInitiative();

    renderSection(InitiativeSettingsDangerPage, "danger");

    expect(await screen.findByText("Danger zone")).toBeInTheDocument();
  });

  it.each([
    ["members", InitiativeSettingsMembersPage],
    ["roles", InitiativeSettingsRolesPage],
    ["properties", InitiativeSettingsPropertiesPage],
    ["export", InitiativeSettingsExportPage],
    ["danger", InitiativeSettingsDangerPage],
  ])(
    "refuses /settings/%s to a reader who may not configure the initiative",
    async (path, Section) => {
      stubInitiative();

      // The address is typeable, so the section — not the tab bar — is what says no.
      renderSection(Section as React.ComponentType, path as string, "member");

      expect(await screen.findByText("Permission required")).toBeInTheDocument();
    }
  );
});
