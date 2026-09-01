import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

/** The settings frame at one of its section addresses. */
const renderLayout = ({
  path = "",
  role = "admin",
  user,
}: {
  path?: string;
  role?: "admin" | "member";
  user?: UserRead;
} = {}) =>
  renderPage(InitiativeSettingsLayout, {
    guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role }) },
    initialRoute: `/g/$guildId/i/$initiativeId/settings${path}`,
    routeParams: { guildId: "1", initiativeId: String(INITIATIVE_ID) },
    ...(user ? { auth: { user } } : {}),
  });

describe("InitiativeSettingsLayout", () => {
  it("names every section as a tab", async () => {
    stubInitiative();

    renderLayout();

    expect(await screen.findByRole("tab", { name: "Details" })).toBeInTheDocument();
    for (const label of ["Members", "Roles", "Custom properties", "Export", "Danger zone"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("navigates to the section a tab names", async () => {
    stubInitiative();

    const { router } = renderLayout();

    await userEvent.click(await screen.findByRole("tab", { name: "Members" }));

    // The section is an address, not a piece of component state.
    expect(router.state.location.pathname).toBe("/g/1/i/7/settings/members");
  });

  it("lights the tab the address names", async () => {
    stubInitiative();

    renderLayout({ path: "/roles" });

    expect(await screen.findByRole("tab", { name: "Roles" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

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
