/**
 * The project-manager picker on Settings › Initiatives.
 *
 * This table is a guild admin's way into an initiative they have not joined:
 * their sidebar lists only their own memberships, so taking the project manager
 * role here is what brings one into it.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import {
  buildGuild,
  buildInitiative,
  buildInitiativeMember,
  buildUserGuildMember,
  buildUserPublic,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";

import { SettingsInitiativesPage } from "./SettingsInitiativesPage";

const INITIATIVE_ID = 7;
const ADMIN_ID = 1;
const MEMBER_ID = 2;

const PM_ROLE = {
  id: 10,
  initiative_id: INITIATIVE_ID,
  name: "project_manager",
  display_name: "Project Manager",
  is_manager: true,
  is_builtin: true,
  override_share_restrictions: false,
  permissions: {},
};
const MEMBER_ROLE = {
  ...PM_ROLE,
  id: 11,
  name: "member",
  display_name: "Member",
  is_manager: false,
};

/** The roster the picker offers, and the roles it resolves against. */
function stubTable(members: ReturnType<typeof buildInitiativeMember>[]) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  server.use(
    guildHttp.get("/initiatives/", () =>
      HttpResponse.json([buildInitiative({ id: INITIATIVE_ID, name: "Apollo", members })])
    ),
    guildHttp.get("/initiatives/:id/roles", () => HttpResponse.json([PM_ROLE, MEMBER_ROLE])),
    guildHttp.get("/users/", () =>
      HttpResponse.json([
        buildUserGuildMember({
          id: ADMIN_ID,
          username: "ada",
          full_name: "Ada Lovelace",
          guild_role: "admin",
        }),
        buildUserGuildMember({
          id: MEMBER_ID,
          username: "bo",
          full_name: "Bo Diddley",
          guild_role: "member",
        }),
      ])
    ),
    guildHttp.post("/initiatives/:id/members", async ({ request }) => {
      calls.push({ method: "POST", url: "members", body: await request.json() });
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID }));
    }),
    guildHttp.patch("/initiatives/:id/members/:userId", async ({ request, params }) => {
      calls.push({ method: "PATCH", url: String(params.userId), body: await request.json() });
      return HttpResponse.json(buildInitiative({ id: INITIATIVE_ID }));
    }),
    guildHttp.delete("/initiatives/:id/members/:userId", ({ params }) => {
      calls.push({ method: "DELETE", url: String(params.userId) });
      return new HttpResponse(null, { status: 204 });
    })
  );
  return calls;
}

const render = () => {
  const guild = buildGuild({ id: 1, role: "admin" });
  renderPage(() => <SettingsInitiativesPage />, {
    guilds: { guilds: [guild], activeGuildId: guild.id, activeGuild: guild },
  });
};

/** Opens the row's manager picker and ticks (or unticks) one candidate. */
async function pick(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole("combobox", { name: "Project managers" }));
  await user.click(await screen.findByRole("option", { name }));
}

describe("SettingsInitiativesPage project managers", () => {
  it("names the initiative's managers, and says so when it has none", async () => {
    stubTable([]);
    render();

    expect(await screen.findByRole("combobox", { name: "Project managers" })).toHaveTextContent(
      "None"
    );
  });

  it("adds a guild admin who is in no initiative as its project manager", async () => {
    const calls = stubTable([]);
    const user = userEvent.setup();
    render();

    await pick(user, "Ada Lovelace");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "POST",
      body: { user_id: ADMIN_ID, role_id: PM_ROLE.id },
    });
  });

  it("promotes an existing member rather than adding them twice", async () => {
    const calls = stubTable([
      buildInitiativeMember({
        user: buildUserPublic({ id: MEMBER_ID, username: "bo" }),
        role_id: MEMBER_ROLE.id,
        role_name: "member",
        is_manager: false,
      }),
    ]);
    const user = userEvent.setup();
    render();

    await pick(user, "Bo Diddley");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "PATCH",
      url: String(MEMBER_ID),
      body: { role_id: PM_ROLE.id },
    });
  });

  it("unticking an ordinary manager leaves them in the initiative as a member", async () => {
    const calls = stubTable([
      buildInitiativeMember({
        user: buildUserPublic({ id: MEMBER_ID, username: "bo" }),
        role_id: PM_ROLE.id,
        role_name: "project_manager",
        is_manager: true,
      }),
    ]);
    const user = userEvent.setup();
    render();

    await pick(user, "Bo Diddley");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "PATCH",
      url: String(MEMBER_ID),
      body: { role_id: MEMBER_ROLE.id },
    });
  });

  it("unticking a guild admin takes their membership away, since they hold no other role", async () => {
    const calls = stubTable([
      buildInitiativeMember({
        user: buildUserPublic({ id: ADMIN_ID, username: "ada" }),
        role_id: PM_ROLE.id,
        role_name: "project_manager",
        is_manager: true,
      }),
    ]);
    const user = userEvent.setup();
    render();

    await pick(user, "Ada Lovelace");

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "DELETE", url: String(ADMIN_ID) });
  });
});
