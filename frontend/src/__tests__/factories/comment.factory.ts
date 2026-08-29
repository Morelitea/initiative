import type { CommentRead, RecentActivityEntry } from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildComment(overrides: Partial<CommentRead> = {}): CommentRead {
  counter++;
  return {
    id: counter,
    content: `Comment content ${counter}`,
    created_by: 1,
    task_id: null,
    document_id: null,
    project_id: null,
    queue_id: null,
    counter_group_id: null,
    calendar_id: null,
    dashboard_id: null,
    parent_comment_id: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: null,
    author: {
      id: 1,
      username: "comment-author",
      discriminator: 1001,
      full_name: "Comment Author",
      avatar_url: null,
    },
    ...overrides,
  };
}

/** An entry of the guild-wide activity feed (`GET /comments/recent`). */
export function buildRecentActivityEntry(
  overrides: Partial<RecentActivityEntry> = {}
): RecentActivityEntry {
  counter++;
  return {
    comment_id: counter,
    content: `Comment content ${counter}`,
    created_at: "2026-01-15T00:00:00.000Z",
    author: {
      id: 1,
      username: "comment-author",
      discriminator: 1001,
      full_name: "Comment Author",
      avatar_url: null,
    },
    task_id: null,
    task_title: null,
    document_id: null,
    document_name: null,
    project_id: null,
    project_name: null,
    entity_type: null,
    entity_id: null,
    entity_name: null,
    initiative_id: null,
    ...overrides,
  };
}
