/**
 * Realtime invalidation drift tests — every tool's comment thread must be
 * reachable from the bus.
 *
 * A comment hangs off a task or any tool entity (backend `_COMMENT_PARENTS`),
 * and the handler derives that from the tool registry rather than a branch per
 * parent. These tests walk `TOOLS`, so adding a tool without a comment
 * invalidation path fails here instead of shipping a thread that only refreshes
 * on reload.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { setInvalidationGuild } from "@/api/query-keys";
import { handleCommentEvent, handleToolEvent } from "@/hooks/useRealtimeUpdates";
import { queryClient } from "@/lib/queryClient";
import { TOOLS, toolIdParam, toolRouteSegment } from "@/lib/tools";

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

describe("realtime comment events", () => {
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
    const list = seed([`/api/v1/g/${GUILD}/${toolRouteSegment(tool)}/`]);

    handleCommentEvent({ comment_id: 1, [toolIdParam(tool)]: ENTITY_ID });

    expect(thread()).toBe(true);
    expect(entity()).toBe(true);
    expect(list()).toBe(true);
  });

  it("refreshes a task's thread, the task, and its project activity", () => {
    const thread = seedThread("task_id", ENTITY_ID);
    const task = seed([`/api/v1/g/${GUILD}/tasks/${ENTITY_ID}`]);
    const activity = seed([`/api/v1/g/${GUILD}/projects/7/activity`]);

    handleCommentEvent({ comment_id: 1, task_id: ENTITY_ID, project_id: 7 });

    expect(thread()).toBe(true);
    expect(task()).toBe(true);
    expect(activity()).toBe(true);
  });

  it("treats a task comment's project id as the task's, not a second parent", () => {
    const projectThread = seedThread("project_id", 7);
    const project = seed([`/api/v1/g/${GUILD}/projects/7`]);

    handleCommentEvent({ comment_id: 1, task_id: ENTITY_ID, project_id: 7 });

    expect(projectThread()).toBe(false);
    expect(project()).toBe(false);
  });

  it("leaves another entity's thread of the same tool alone", () => {
    const mine = seedThread("post_id", ENTITY_ID);
    const theirs = seedThread("post_id", ENTITY_ID + 1);

    handleCommentEvent({ comment_id: 1, post_id: ENTITY_ID });

    expect(mine()).toBe(true);
    expect(theirs()).toBe(false);
  });

  it("refreshes the guild's recent-comments feed", () => {
    const recent = seed([`/api/v1/g/${GUILD}/comments/recent`]);

    handleCommentEvent({ comment_id: 1, post_id: ENTITY_ID });

    expect(recent()).toBe(true);
  });

  it("ignores a frame that names no parent", () => {
    const thread = seedThread("post_id", ENTITY_ID);

    handleCommentEvent({ comment_id: 1 });

    expect(thread()).toBe(false);
  });
});

describe("realtime tool events", () => {
  beforeEach(() => {
    queryClient.clear();
    setInvalidationGuild(GUILD);
  });

  afterEach(() => {
    queryClient.clear();
    setInvalidationGuild(null);
  });

  // Every write to a notice arrives this way — posted, published on schedule,
  // edited, pinned, deleted, voted in, reacted to. The board and the notice's
  // own page both read the post, so both are refreshed.
  it("refreshes a notice and the board it is on", () => {
    const post = seed([`/api/v1/g/${GUILD}/posts/${ENTITY_ID}`]);
    const board = seed([`/api/v1/g/${GUILD}/posts/`]);
    const timeline = seed([`/api/v1/g/${GUILD}/posts/timeline`]);

    handleToolEvent(Tool.post, { post_id: ENTITY_ID });

    expect(post()).toBe(true);
    expect(board()).toBe(true);
    expect(timeline()).toBe(true);
  });

  it("does nothing when the envelope carries no id", () => {
    const post = seed([`/api/v1/g/${GUILD}/posts/${ENTITY_ID}`]);

    handleToolEvent(Tool.post, {});

    expect(post()).toBe(false);
  });
});
