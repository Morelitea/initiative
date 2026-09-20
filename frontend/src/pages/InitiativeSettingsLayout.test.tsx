import { screen } from "@testing-library/react";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildGuild,
  buildInitiative,
  buildInitiativeMember,
  buildUser,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { UserRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { InitiativeSettingsLayout } from "./InitiativeSettingsLayout";

const INITIATIVE_ID = 7;

function stubInitiative(members: unknown[] = []) {
  server.use(
    guildHttp.get("/initiatives/:id", () =>
      HttpResponse.json(buildInitiative({ id: INITIATIVE_ID, name: "Apollo", members }))
    )
  );
}

/** The settings frame, for a reader with the given standing. */
const renderLayout = ({
  role = "admin",
  user,
}: {
  role?: "admin" | "member";
  user?: UserRead;
} = {}) =>
  renderPage(InitiativeSettingsLayout, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
    initialRoute: "/c/$guildId/i/$initiativeId/settings",
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
    ...(user ? { auth: { user } } : {}),
  });

/**
 * How the bar itself behaves — naming every section, navigating to the one a
 * tab names, lighting the one the address names — is the shared
 * `SettingsTabsNav`, proved once in
 * `src/components/tools/settings/ToolSettingsLayout.test.tsx`. What is left
 * here is who gets a bar at all, which only this layout decides.
 */
describe("InitiativeSettingsLayout", () => {
  it("keeps the export tab out of the bar for someone who may not export", async () => {
    // A plain guild member who manages nothing here: the layout still refuses
    // the whole surface, so no section is offered at all.
    stubInitiative();

    renderLayout({ role: "member" });

    expect(await screen.findByText("Permission required")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Export" })).not.toBeInTheDocument();
  });

  it("lets an initiative manager who is no guild admin in", async () => {
    const user = buildUser({ id: 42 });
    stubInitiative([
      buildInitiativeMember({ user: { ...user, id: 42 }, is_manager: true, role_name: "manager" }),
    ]);

    renderLayout({ role: "member", user });

    expect(await screen.findByRole("tab", { name: "Members" })).toBeInTheDocument();
  });

  it("says so when the initiative isn't one this reader can see", async () => {
    server.use(guildHttp.get("/initiatives/:id", () => new HttpResponse(null, { status: 404 })));

    renderLayout();

    expect(await screen.findByText("Initiative not found")).toBeInTheDocument();
  });
});
