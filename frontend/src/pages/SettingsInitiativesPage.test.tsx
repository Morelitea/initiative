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
  buildPage,
  buildUserPublic,
  buildUserSummary,
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

/** The initiative's managers, as the picker asks for them, and the roles it
 *  resolves against. */
function stubTable(managers: ReturnType<typeof buildInitiativeMember>[]) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  server.use(
    guildHttp.get("/initiatives/", () =>
      HttpResponse.json([buildInitiative({ id: INITIATIVE_ID, name: "Apollo", member_count: 3 })])
    ),
    // Only the managers: an answer to anything wider would hand the picker
    // people who are not.
    guildHttp.get("/initiatives/:id/members", ({ request }) =>
      new URL(request.url).searchParams.get("is_manager") === "true"
        ? HttpResponse.json(buildPage(managers))
        : HttpResponse.json({ detail: "unexpected roster read" }, { status: 400 })
    ),
    guildHttp.get("/initiatives/:id/roles", () => HttpResponse.json([PM_ROLE, MEMBER_ROLE])),
    // The guild's member search — what the picker offers, and how it learns
    // whether a manager is a guild admin.
    guildHttp.get("/users/search", () =>
      HttpResponse.json(
        buildPage([
          buildUserSummary({
            id: ADMIN_ID,
            username: "ada",
            display_name: "Ada Lovelace",
            community_role: "admin",
          }),
          buildUserSummary({
            id: MEMBER_ID,
            username: "bo",
            display_name: "Bo Diddley",
            community_role: "member",
          }),
        ])
      )
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
    // The headcount is the row's own, not a roster read per row.
    expect(screen.getByText("3 members")).toBeInTheDocument();
  });

  it("reads every manager, starting again when the roster changes between pages", async () => {
    stubTable([]);
    const ada = buildInitiativeMember({
      user: buildUserPublic({ id: ADMIN_ID, display_name: "Ada Lovelace" }),
    });
    const bo = buildInitiativeMember({
      user: buildUserPublic({ id: MEMBER_ID, display_name: "Bo Diddley" }),
    });
    const asked: number[] = [];
    server.use(
      guildHttp.get("/initiatives/:id/members", ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page"));
        asked.push(page);
        // The first ask for page 2 lands after a change: past the end, so the
        // server answers with page 1 again.
        const served = page === 2 && asked.filter((p) => p === 2).length > 1 ? 2 : 1;
        return HttpResponse.json(
          buildPage(served === 1 ? [ada] : [bo], { page: served, has_next: served === 1 })
        );
      })
    );
    render();

    expect(await screen.findByRole("combobox", { name: "Project managers" })).toHaveTextContent(
      "2 managers"
    );
    expect(asked).toEqual([1, 2, 2]);
  });

  // The same call promotes someone already in it: the server moves an existing
  // member onto the role it names rather than adding them twice.
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
