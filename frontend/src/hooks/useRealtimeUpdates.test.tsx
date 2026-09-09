/**
 * Realtime invalidation drift tests — what a frame off the bus refreshes.
 *
 * The bus names a resource and the resources it sits inside, both as
 * `{type, id}` and both addressed the same way (backend `event_outbox.parents`).
 * The handler derives its work from the tool registry rather than a branch per
 * kind, so these walk `TOOLS`: adding a tool without an invalidation path fails
 * here instead of shipping a thread that only refreshes on reload.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { latestSocket, MockWebSocket } from "@/__tests__/helpers/mockWebSocket";
import { renderWithProviders } from "@/__tests__/helpers/render";
import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { setInvalidationGuild } from "@/api/query-keys";
import { applyChanges, useRealtimeUpdates } from "@/hooks/useRealtimeUpdates";
import { queryClient } from "@/lib/queryClient";
import { TOOLS, toolIdParam, toolPlural, toolRouteSegment } from "@/lib/tools";

const GUILD = 5;
const ENTITY_ID = 42;
// Must match the backend's MSG_AUTH.
const MSG_AUTH = 5;

// The hook keys its socket off the route's guild; the tests drive the socket
// rather than the router, so the param is stated directly.
vi.mock("@tanstack/react-router", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-router")>()),
  useParams: () => ({ guildId: String(GUILD) }),
}));

/** Seed a query so it exists in the cache, then report whether it got invalidated. */
const seed = (key: readonly unknown[]) => {
  queryClient.setQueryData(key, { seeded: true });
  return () => queryClient.getQueryState(key)?.isInvalidated ?? false;
};

/** The comment-thread query for one parent, as `useComments` keys it. */
const seedThread = (param: string, id: number) =>
  seed([`/api/v1/g/${GUILD}/comments/`, { [param]: id }]);

const comment = (id: number, parents: { type: string; id: number }[]) => ({
  resource: { type: "comments", id },
  parents,
  action: "created",
});

describe("realtime comment frames", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationGuild(GUILD);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  it.each(TOOLS)("refreshes a %s's thread and the entity around it", (tool) => {
    const thread = seedThread(toolIdParam(tool), ENTITY_ID);
    const entity = seed([`/api/v1/g/${GUILD}/${toolRouteSegment(tool)}/${ENTITY_ID}`]);

    applyChanges([comment(1, [{ type: toolPlural(tool), id: ENTITY_ID }])]);

    expect(thread(), `${tool} thread`).toBe(true);
    expect(entity(), `${tool} entity`).toBe(true);
  });

  it("refreshes the thread, the task and the task's project", () => {
    const thread = seedThread("task_id", ENTITY_ID);
    const task = seed([`/api/v1/g/${GUILD}/tasks/${ENTITY_ID}`]);
    const activity = seed([`/api/v1/g/${GUILD}/projects/7/activity`]);
    const project = seed([`/api/v1/g/${GUILD}/projects/7`]);

    applyChanges([
      comment(1, [
        { type: "tasks", id: ENTITY_ID },
        { type: "projects", id: 7 },
      ]),
    ]);

    expect(thread(), "thread").toBe(true);
    expect(task(), "task").toBe(true);
    expect(activity(), "project activity").toBe(true);
    expect(project(), "project").toBe(true);
  });

  it("refreshes the guild's recent activity for any comment", () => {
    const recent = seed([`/api/v1/g/${GUILD}/comments/recent`]);

    applyChanges([comment(1, [{ type: "posts", id: ENTITY_ID }])]);

    expect(recent()).toBe(true);
  });

  it("leaves another entity's thread alone", () => {
    const other = seedThread("post_id", 99);

    applyChanges([comment(1, [{ type: "posts", id: ENTITY_ID }])]);

    expect(other()).toBe(false);
  });

  it("refreshes each thing once for a batch that names it many times", () => {
    const thread = seedThread("task_id", ENTITY_ID);
    const parents = [
      { type: "tasks", id: ENTITY_ID },
      { type: "projects", id: 7 },
    ];

    applyChanges([comment(1, parents), comment(2, parents), comment(3, parents)]);

    expect(thread()).toBe(true);
  });
});

describe("realtime resource frames", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationGuild(GUILD);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  it.each(TOOLS)("refreshes a %s that changed", (tool) => {
    const entity = seed([`/api/v1/g/${GUILD}/${toolRouteSegment(tool)}/${ENTITY_ID}`]);

    applyChanges([
      { resource: { type: toolPlural(tool), id: ENTITY_ID }, parents: [], action: "updated" },
    ]);

    expect(entity()).toBe(true);
  });

  it("refreshes a task's project from the task's own frame", () => {
    const task = seed([`/api/v1/g/${GUILD}/tasks/${ENTITY_ID}`]);
    const project = seed([`/api/v1/g/${GUILD}/projects/7`]);

    applyChanges([
      {
        resource: { type: "tasks", id: ENTITY_ID },
        parents: [{ type: "projects", id: 7 }],
        action: "updated",
      },
    ]);

    expect(task(), "task").toBe(true);
    expect(project(), "project").toBe(true);
  });

  it("refreshes a task's subtask list from a subtask frame", () => {
    const subtasks = seed([`/api/v1/g/${GUILD}/tasks/${ENTITY_ID}/subtasks`]);

    applyChanges([
      {
        resource: { type: "subtasks", id: 3 },
        parents: [
          { type: "tasks", id: ENTITY_ID },
          { type: "projects", id: 7 },
        ],
        action: "created",
      },
    ]);

    expect(subtasks()).toBe(true);
  });

  it("refreshes the roster, the roles and what they permit", () => {
    // A membership row and a role row have no route of their own, so all three
    // of these report as the initiative — one frame has to cover them.
    const initiative = seed([`/api/v1/g/${GUILD}/initiatives/${ENTITY_ID}`]);
    const members = seed([`/api/v1/g/${GUILD}/initiatives/${ENTITY_ID}/members`]);
    const roles = seed([`/api/v1/g/${GUILD}/initiatives/${ENTITY_ID}/roles`]);
    const permissions = seed([`/api/v1/g/${GUILD}/initiatives/${ENTITY_ID}/my-permissions`]);

    applyChanges([
      { resource: { type: "initiatives", id: ENTITY_ID }, parents: [], action: "updated" },
    ]);

    expect(initiative(), "initiative").toBe(true);
    expect(members(), "members").toBe(true);
    expect(roles(), "roles").toBe(true);
    expect(permissions(), "my permissions").toBe(true);
  });

  it("refreshes the app list and an install's own reads", () => {
    // Guild-wide and parentless: nothing else on the client covers it.
    const list = seed([`/api/v1/g/${GUILD}/apps/`]);
    const detail = seed(["guild-app", GUILD, ENTITY_ID]);
    const members = seed(["guild-app-members", GUILD, ENTITY_ID]);

    applyChanges([{ resource: { type: "apps", id: ENTITY_ID }, parents: [], action: "updated" }]);

    expect(list(), "app list").toBe(true);
    expect(detail(), "app detail").toBe(true);
    expect(members(), "app members").toBe(true);
  });

  it("leaves another guild's install reads alone", () => {
    const other = seed(["guild-app", GUILD + 1, ENTITY_ID]);

    applyChanges([{ resource: { type: "apps", id: ENTITY_ID }, parents: [], action: "created" }]);

    expect(other()).toBe(false);
  });

  it("ignores a resource type it has no invalidation for", () => {
    const untouched = seed([`/api/v1/g/${GUILD}/tasks/${ENTITY_ID}`]);

    expect(() =>
      applyChanges([{ resource: { type: "something_new", id: 1 }, parents: [], action: "created" }])
    ).not.toThrow();
    expect(untouched()).toBe(false);
  });

  it("ignores a malformed frame rather than throwing", () => {
    expect(() => applyChanges([{}, { resource: undefined, parents: undefined }])).not.toThrow();
  });

  it("still refreshes the parents when the resource itself is unknown", () => {
    const project = seed([`/api/v1/g/${GUILD}/projects/7`]);

    applyChanges([
      {
        resource: { type: "queue_items", id: 3 },
        parents: [{ type: "projects", id: 7 }],
        action: "updated",
      },
    ]);

    expect(project()).toBe(true);
  });
});

describe("Tool.project is the one resource with an activity feed", () => {
  it("names the project tool by its plural, like the bus does", () => {
    expect(toolPlural(Tool.project)).toBe("projects");
  });
});

/**
 * The socket around those frames: what it says on the way up, and how it
 * notices it has stopped carrying.
 *
 * This bus has no poll behind it — a socket that quietly dies takes live
 * updates with it until something else refetches — so both halves are load
 * bearing: the server's beat is what silence is measured against, and the gap
 * a reconnect names is what the server answers with "something moved".
 */
const Probe = () => {
  useRealtimeUpdates();
  return null;
};

describe("realtime socket lifecycle", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    queryClient.clear();
    setInvalidationGuild(GUILD);
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    queryClient.clear();
    setInvalidationGuild(null);
  });

  it("authenticates in the first frame and names no gap", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();

    expect(socket.url).not.toContain("token");
    expect(socket.sent[0][0]).toBe(MSG_AUTH);
    // A tab that has only just mounted fetched what it is showing.
    expect(socket.authPayload()).toEqual({ token: "test-token" });
  });

  it("tells the server how long it was without a socket, dated from the last frame", async () => {
    renderWithProviders(<Probe />);
    const first = latestSocket();
    first.open();

    // Quiet for a minute, then gone. The gap starts where the frames stopped,
    // not where the close was noticed.
    await vi.advanceTimersByTimeAsync(60_000);
    first.serverClose(1006);
    await vi.advanceTimersByTimeAsync(2000);

    const second = latestSocket();
    expect(second).not.toBe(first);
    second.open();
    expect(second.authPayload()).toEqual({ token: "test-token", away_seconds: 62 });
  });

  it("reads the guild again when the server says it fell behind", () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    const project = seed([`/api/v1/g/${GUILD}/projects/${ENTITY_ID}`]);

    socket.receive({ changes: [], more: true });

    expect(project()).toBe(true);
  });

  it("ignores a beat beyond taking it as proof of life", async () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();
    const project = seed([`/api/v1/g/${GUILD}/projects/${ENTITY_ID}`]);

    socket.receive({ heartbeat: true });
    await vi.advanceTimersByTimeAsync(1000);

    expect(project()).toBe(false);
    expect(socket.closed).toBe(false);
  });

  it("closes a socket the server has gone silent on", async () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();

    // Past the limit, and past the next check after it.
    await vi.advanceTimersByTimeAsync(110_000);

    expect(socket.closed).toBe(true);
  });

  it("keeps a socket the server is still beating on", async () => {
    renderWithProviders(<Probe />);
    const socket = latestSocket();
    socket.open();

    for (let elapsed = 0; elapsed < 95_000; elapsed += 30_000) {
      await vi.advanceTimersByTimeAsync(30_000);
      socket.receive({ heartbeat: true });
    }

    expect(socket.closed).toBe(false);
  });
});
