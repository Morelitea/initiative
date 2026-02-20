// Auto-generated types — do not edit manually (except backward-compat aliases below)
// Run `pnpm generate:api` to regenerate from backend OpenAPI spec

// Re-export all generated types and const enums
export * from "@/api/generated/initiativeAPI.schemas";

// ─── Backward-compatible aliases ───────────────────────────────────────────
// The generated schema uses Read/Response suffixes and has broader optionality
// than the manual types the codebase was written against. These aliases preserve
// existing import names and field requirements.

import type { ProjectRead } from "@/api/generated/initiativeAPI.schemas";

// --- Paginated response wrappers (frontend-only; not in the OpenAPI spec) ---
// TaskListResponse and DocumentListResponse are now generated — see initiativeAPI.schemas.
// ProjectListResponse remains frontend-only (projects endpoint isn't paginated).

export type ProjectListResponse = {
  items: ProjectRead[];
  total_count: number;
  page: number;
  page_size: number;
};

// --- Types not in the OpenAPI spec (frontend-only constructs) ---

export type TaskWeekPosition = "first" | "second" | "third" | "fourth" | "last";

export type PermissionKey = "docs_enabled" | "projects_enabled" | "create_docs" | "create_projects";

export type MentionEntityType = "user" | "task" | "doc" | "project";

import type { CommentRead } from "@/api/generated/initiativeAPI.schemas";

export interface CommentWithReplies extends CommentRead {
  replies: CommentWithReplies[];
}
