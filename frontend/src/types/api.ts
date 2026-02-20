// Auto-generated types — do not edit manually (except backward-compat aliases below)
// Run `pnpm generate:api` to regenerate from backend OpenAPI spec

// Re-export all generated types and const enums
export * from "@/api/generated/initiativeAPI.schemas";

// ─── Backward-compatible aliases ───────────────────────────────────────────
// The generated schema uses Read/Response suffixes and has broader optionality
// than the manual types the codebase was written against. These aliases preserve
// existing import names and field requirements.

import type {
  InitiativeRead,
  InitiativeMemberRead,
  ProjectRead,
  TaskListRead,
  TagRead,
  TaskAssigneeSummary,
  ProjectPermissionRead,
  ProjectTaskSummary as GenProjectTaskSummary,
} from "@/api/generated/initiativeAPI.schemas";

// --- Aliases where the generated type has optional fields the codebase treats as required ---

/** Initiative with members guaranteed present */
export type Initiative = Omit<InitiativeRead, "members"> & {
  members: InitiativeMemberRead[];
};

/**
 * Unified Task type that covers both list and detail shapes.
 * The codebase treats flat guild/project/initiative fields (from TaskListRead)
 * and nested objects (from TaskRead) as all-present on a single Task type.
 */
export type Task = Omit<TaskListRead, "assignees"> & {
  assignees: TaskAssigneeSummary[];
  priority: TaskListRead["priority"] & string; // ensure non-optional
  is_archived: boolean;
};

/** Tag with required color field */
export type Tag = Omit<TagRead, "color"> & { color: string };

/** Project with required permissions array */
export type Project = Omit<ProjectRead, "permissions"> & {
  permissions: ProjectPermissionRead[];
};

/** ProjectTaskSummary with required fields */
export type ProjectTaskSummary = Required<GenProjectTaskSummary>;

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

export type TaskRecurrenceStrategy = "fixed" | "rolling";

export type PermissionKey = "docs_enabled" | "projects_enabled" | "create_docs" | "create_projects";

export type MentionEntityType = "user" | "task" | "doc" | "project";

import type { CommentRead } from "@/api/generated/initiativeAPI.schemas";

export interface CommentWithReplies extends CommentRead {
  replies: CommentWithReplies[];
}
