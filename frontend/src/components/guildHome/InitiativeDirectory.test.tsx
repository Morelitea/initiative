import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import {
  buildGuild,
  buildInitiative,
  buildInitiativeDirectoryEntry,
  buildInitiativeJoinRequest,
  buildInitiativeMember,
  buildUser,
} from "@/__tests__/factories";
import { guildHttp } from "@/__tests__/helpers/guildHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderPage } from "@/__tests__/helpers/render";
import type { InitiativeDirectoryEntry, UserRead } from "@/api/generated/initiativeAPI.schemas";

vi.mock("@/lib/chesterToast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { toast } from "@/lib/chesterToast";
import { getItem } from "@/lib/storage";

import { InitiativeDirectory } from "./InitiativeDirectory";

const OPEN_ID = 5;

/** The memory router mounts asynchronously, so every test awaits its first
 *  query. The marker gives the empty case something to wait for. */
const renderDirectory = (entries: InitiativeDirectoryEntry[], user?: UserRead) =>
  renderPage(
    () => (
      <>
        <div data-testid="mounted" />
        <InitiativeDirectory entries={entries} />
      </>
    ),
    {
      guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1 }) },
      ...(user ? { auth: { user } } : {}),
    }
  );

const openEntry = () =>
  buildInitiativeDirectoryEntry({ id: OPEN_ID, name: "Nebula", join_policy: "open" });

const REQUEST_ID = 6;

const requestEntry = (overrides: Partial<InitiativeDirectoryEntry> = {}) =>
  buildInitiativeDirectoryEntry({
    id: REQUEST_ID,
    name: "Vanguard",
    join_policy: "request",
    ...overrides,
  });

/** The group a heading names, so a card can be asserted to be in one. */
const group = (name: string) => screen.getByRole("heading", { name }).parentElement as HTMLElement;

describe("InitiativeDirectory", () => {
  it("offers Join only on an initiative anyone can join", async () => {
    renderDirectory([
      openEntry(),
      buildInitiativeDirectoryEntry({ id: 6, name: "Vanguard", join_policy: "request" }),
    ]);

    // A request-policy card asks rather than walks in, so exactly one card
    // carries the Join button.
    expect(await screen.findByText("Vanguard")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Join" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Request to join" })).toBeInTheDocument();
  });

  it("splits the ones you're in from the ones you could join", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({ id: 7, name: "Apollo", is_member: true }),
      openEntry(),
    ]);

    expect(await screen.findByRole("heading", { name: "Your initiatives" })).toBeInTheDocument();
    expect(within(group("Your initiatives")).getByText("Apollo")).toBeInTheDocument();
    expect(within(group("Open to join")).getByText("Nebula")).toBeInTheDocument();
  });

  it("leaves out a group with nothing in it", async () => {
    renderDirectory([openEntry()]);

    expect(await screen.findByRole("heading", { name: "Open to join" })).toBeInTheDocument();
    // No heading over an empty grid.
    expect(screen.queryByRole("heading", { name: "Your initiatives" })).not.toBeInTheDocument();
  });

  it("leads into an initiative you're in from its title", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({
        id: 7,
        name: "Apollo",
        join_policy: "open",
        is_member: true,
      }),
    ]);

    // The title is the way in — there is no second button saying the same.
    expect(await screen.findByRole("link", { name: "Apollo" })).toHaveAttribute("href", "/g/1/i/7");
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("leaves a title you cannot enter as plain text", async () => {
    renderDirectory([openEntry()]);

    expect(await screen.findByText("Nebula")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nebula" })).not.toBeInTheDocument();
  });

  it("shows the reader's own private initiative as theirs, never as joinable", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({
        id: 9,
        name: "Skunkworks",
        join_policy: "private",
        is_member: true,
      }),
    ]);

    // A member's private initiative rounds out the list: in their own group,
    // labeled invite-only, with nothing offered to anyone else's eyes.
    expect(await screen.findByText("Invite only")).toBeInTheDocument();
    expect(within(group("Your initiatives")).getByText("Skunkworks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("hands a guild admin the whole guild, entered by standing", async () => {
    renderPage(
      () => (
        <InitiativeDirectory
          entries={[
            buildInitiativeDirectoryEntry({
              id: 11,
              name: "Hidden",
              join_policy: "private",
              is_member: false,
            }),
          ]}
        />
      ),
      { guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) } }
    );

    // A private initiative the admin is not in is theirs to reach, not on
    // offer: it sits in their own group, badged with why, title as the way in.
    expect(await screen.findByRole("heading", { name: "Your initiatives" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Open to join" })).not.toBeInTheDocument();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Hidden" })).toHaveAttribute("href", "/g/1/i/11");
    expect(screen.queryByRole("button", { name: "Join" })).not.toBeInTheDocument();
  });

  it("still offers an admin an open initiative they are not in", async () => {
    renderPage(
      () => (
        <InitiativeDirectory
          entries={[
            buildInitiativeDirectoryEntry({
              id: 12,
              name: "Nebula",
              join_policy: "open",
              is_member: false,
            }),
          ]}
        />
      ),
      { guilds: { activeGuildId: 1, activeGuild: buildGuild({ id: 1, role: "admin" }) } }
    );

    // An admin can reach it either way, so it stays on offer rather than being
    // filed as theirs — and the card carries one way in, never both.
    expect(await screen.findByRole("heading", { name: "Open to join" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Join" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nebula" })).not.toBeInTheDocument();
  });

  it("names the reader's role on a card they're in", async () => {
    const user = buildUser({ id: 42 });
    server.use(
      guildHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({
            id: 7,
            name: "Apollo",
            members: [
              buildInitiativeMember({
                user: { ...user, id: 42 },
                role_name: "project_manager",
                role_display_name: "Project Manager",
                is_manager: true,
              }),
            ],
          }),
        ])
      )
    );

    renderDirectory(
      [buildInitiativeDirectoryEntry({ id: 7, name: "Apollo", is_member: true })],
      user
    );

    // The badge says WHAT you are there, which already implies that you're in.
    expect(await screen.findByText("Project Manager")).toBeInTheDocument();
    expect(screen.queryByText("Joined")).not.toBeInTheDocument();
  });

  it("counts what is inside an initiative you're in, tool by tool", async () => {
    const user = buildUser({ id: 42 });
    server.use(
      guildHttp.get("/initiatives/", () =>
        HttpResponse.json([
          buildInitiative({
            id: 7,
            name: "Apollo",
            queues_enabled: true,
            members: [
              buildInitiativeMember({
                user: { ...user, id: 42 },
                can_view_projects: true,
                can_view_queues: true,
                // Calendars stay off for this member, so they get no stat.
                can_view_calendars: false,
              }),
            ],
          }),
        ])
      ),
      guildHttp.get("/projects/counts/by-initiative", () =>
        HttpResponse.json({ counts: { "7": 3 } })
      ),
      guildHttp.get("/queues/counts/by-initiative", () => HttpResponse.json({ counts: { "7": 2 } }))
    );

    renderDirectory(
      [buildInitiativeDirectoryEntry({ id: 7, name: "Apollo", is_member: true })],
      user
    );

    expect(await screen.findByText("Projects: 3")).toBeInTheDocument();
    expect(screen.getByText("Queues: 2")).toBeInTheDocument();
    // A tool this member can't view has no number to report.
    expect(screen.queryByText(/^Calendar:/)).not.toBeInTheDocument();
  });

  it("leaves a card you're not in free of counts", async () => {
    renderDirectory([openEntry()]);

    expect(await screen.findByText("Nebula")).toBeInTheDocument();
    expect(screen.queryByText(/^Projects:/)).not.toBeInTheDocument();
  });

  it("names each initiative's roster size", async () => {
    renderDirectory([buildInitiativeDirectoryEntry({ name: "Nebula", member_count: 1 })]);

    expect(await screen.findByText("1 member")).toBeInTheDocument();
  });

  it("collapses the whole section from its heading, and remembers it", async () => {
    const { unmount } = renderDirectory([openEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: /Initiatives/ }));

    await waitFor(() => expect(screen.queryByText("Nebula")).not.toBeInTheDocument());
    expect(getItem("guildHome.initiatives.collapsed.1")).toBe("true");

    // Coming back to this guild finds the section as it was left.
    unmount();
    renderDirectory([openEntry()]);
    await screen.findByTestId("mounted");
    expect(screen.queryByText("Nebula")).not.toBeInTheDocument();
  });

  it("sends a request to join, with the note the reader wrote", async () => {
    const requests: Array<{ id: string; body: unknown }> = [];
    server.use(
      guildHttp.post("/initiatives/:id/join-requests", async ({ params, request }) => {
        requests.push({ id: String(params.id), body: await request.json() });
        return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: 6 }), {
          status: 201,
        });
      })
    );

    renderDirectory([requestEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.type(await screen.findByLabelText(/Message/), "I run the Thursday session.");
    await userEvent.click(screen.getByRole("button", { name: "Send request" }));

    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0]).toEqual({
      id: String(REQUEST_ID),
      body: { message: "I run the Thursday session." },
    });
    expect(toast.success).toHaveBeenCalledWith("Your request to join Vanguard was sent.");
  });

  it("sends a request with no note at all", async () => {
    const bodies: unknown[] = [];
    server.use(
      guildHttp.post("/initiatives/:id/join-requests", async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(buildInitiativeJoinRequest({ initiative_id: 6 }), {
          status: 201,
        });
      })
    );

    renderDirectory([requestEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // The note is optional, and an empty one is sent as no note rather than "".
    await waitFor(() => expect(bodies).toEqual([{ message: null }]));
  });

  it("shows a knock already waiting as a state, not a button", async () => {
    renderDirectory([requestEntry({ has_pending_request: true })]);

    expect(await screen.findByText("Requested")).toBeInTheDocument();
    // Nothing the requester can press moves it along.
    expect(screen.queryByRole("button", { name: "Request to join" })).not.toBeInTheDocument();
  });

  it("explains a refused request in the reader's own words", async () => {
    server.use(
      guildHttp.post("/initiatives/:id/join-requests", () =>
        HttpResponse.json({ detail: "INITIATIVE_JOIN_REQUEST_ALREADY_PENDING" }, { status: 409 })
      )
    );

    renderDirectory([requestEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Request to join" }));
    await userEvent.click(await screen.findByRole("button", { name: "Send request" }));

    // The backend answers with a code; the reader gets the mapped sentence.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "You already have a request waiting on this initiative"
      )
    );
  });

  it("tells a manager how many are waiting at their own door", async () => {
    renderDirectory([
      buildInitiativeDirectoryEntry({
        id: 7,
        name: "Apollo",
        join_policy: "request",
        is_member: true,
        pending_join_request_count: 3,
      }),
    ]);

    // The count reads zero for anyone who couldn't answer the queue, so its
    // presence is the permission check.
    expect(await screen.findByText("3 waiting to join")).toBeInTheDocument();
    // And it leads to the queue itself, which is a route of its own.
    expect(screen.getByRole("link", { name: "3 waiting to join" })).toHaveAttribute(
      "href",
      "/g/1/i/7/settings/members"
    );
  });

  it("leaves the waiting count off a card with nobody waiting", async () => {
    renderDirectory([requestEntry()]);

    expect(await screen.findByText("Vanguard")).toBeInTheDocument();
    expect(screen.queryByText(/waiting to join/)).not.toBeInTheDocument();
  });

  it("joins an open initiative and says so", async () => {
    const joined: string[] = [];
    server.use(
      guildHttp.post("/initiatives/:id/join", ({ params }) => {
        joined.push(String(params.id));
        return HttpResponse.json(buildInitiative({ id: OPEN_ID, name: "Nebula" }));
      })
    );

    renderDirectory([openEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    await waitFor(() => expect(joined).toEqual([String(OPEN_ID)]));
    expect(toast.success).toHaveBeenCalledWith("You joined Nebula.");
  });

  it("explains a refused join in the reader's own words", async () => {
    server.use(
      guildHttp.post("/initiatives/:id/join", () =>
        HttpResponse.json({ detail: "INITIATIVE_NOT_JOINABLE" }, { status: 403 })
      )
    );

    renderDirectory([openEntry()]);

    await userEvent.click(await screen.findByRole("button", { name: "Join" }));

    // The backend answers with a code; the reader gets the mapped sentence.
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This initiative isn't open to join")
    );
  });

  it("renders nothing when the guild lists no initiatives", async () => {
    renderDirectory([]);

    await screen.findByTestId("mounted");
    expect(screen.queryByRole("heading", { name: "Initiatives" })).not.toBeInTheDocument();
  });
});
