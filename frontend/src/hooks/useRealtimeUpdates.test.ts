/**
 * Realtime invalidation drift tests — what a frame off the bus refreshes.
 *
 * The bus names a resource and the resources it sits inside, both as
 * `{type, id}` and both addressed the same way (backend `event_outbox.parents`).
 * The handler derives its work from the tool registry rather than a branch per
 * kind, so these walk `TOOLS`: adding a tool without an invalidation path fails
 * here instead of shipping a thread that only refreshes on reload.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { setInvalidationGuild } from "@/api/query-keys";
import { applyChanges } from "@/hooks/useRealtimeUpdates";
import { queryClient } from "@/lib/queryClient";
import { TOOLS, toolIdParam, toolPlural, toolRouteSegment } from "@/lib/tools";

const GUILD = 5;
const ENTITY_ID = 42;

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
