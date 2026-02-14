import type { Comment } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildComment(overrides: Partial<Comment> = {}): Comment {
  counter++;
  return {
    id: counter,
    content: `Comment content ${counter}`,
    author_id: 1,
    task_id: null,
    document_id: null,
    parent_comment_id: null,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: null,
    author: {
      id: 1,
      email: "author@example.com",
      full_name: "Comment Author",
      avatar_url: null,
      avatar_base64: null,
    },
    ...overrides,
  };
}
