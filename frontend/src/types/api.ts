// Auto-generated types — do not edit manually (except backward-compat aliases below)
// Run `pnpm generate:api` to regenerate from backend OpenAPI spec

// Re-export all generated types and const enums
export * from "@/api/generated/initiativeAPI.schemas";

// ─── Backward-compatible aliases ───────────────────────────────────────────
// The generated schema uses Read/Response suffixes and has broader optionality
// than the manual types the codebase was written against. These aliases preserve
// existing import names and field requirements.

import type {
  UserRead,
  GuildRead,
  InitiativeRead,
  InitiativeMemberRead,
  ProjectRead,
  TaskListRead,
  CommentRead,
  TagRead,
  NotificationRead,
  TaskStatusRead,
  SubtaskRead,
  TaskAssigneeSummary,
  GuildSummary,
  RoleLabelsResponse,
  EmailSettingsResponse,
  PlatformAISettingsResponse,
  GuildAISettingsResponse,
  UserAISettingsResponse,
  ResolvedAISettingsResponse,
  ProjectPermissionRead,
  DocumentPermissionRead,
  ProjectRolePermissionRead,
  DocumentRolePermissionRead,
  TaskReorderRequest,
  TaskMoveRequest,
  ProjectReorderRequest,
  DocumentSummaryDocumentType,
  TaskRecurrenceOutput,
  TaskRecurrenceOutputFrequency,
  TaskRecurrenceOutputWeekdaysItem,
  AdminDeletionEligibilityResponse,
  ProjectDocumentSummary,
  ProjectTaskSummary as GenProjectTaskSummary,
} from "@/api/generated/initiativeAPI.schemas";

// --- Simple renames (no shape changes) ---
export type User = UserRead;
export type Guild = GuildRead;
export type TaskMovePayload = TaskMoveRequest;
export type TaskReorderPayload = TaskReorderRequest;
export type ProjectReorderPayload = ProjectReorderRequest;
export type DocumentType = DocumentSummaryDocumentType;
export type TaskRecurrence = TaskRecurrenceOutput;
export type TaskRecurrenceFrequency = TaskRecurrenceOutputFrequency;
export type TaskWeekday = TaskRecurrenceOutputWeekdaysItem;
export type Notification = NotificationRead;
export type RoleLabels = RoleLabelsResponse;
export type EmailSettings = EmailSettingsResponse;
export type PlatformAISettings = PlatformAISettingsResponse;
export type GuildAISettings = GuildAISettingsResponse;
export type UserAISettings = UserAISettingsResponse;
export type ResolvedAISettings = ResolvedAISettingsResponse;
export type ProjectPermission = ProjectPermissionRead;
export type DocumentPermission = DocumentPermissionRead;
export type ProjectRolePermission = ProjectRolePermissionRead;
export type DocumentRolePermission = DocumentRolePermissionRead;
export type TaskGuildSummary = GuildSummary;

// --- Aliases where the generated type has optional fields the codebase treats as required ---

/** Initiative with members guaranteed present */
export type Initiative = Omit<InitiativeRead, "members"> & {
  members: InitiativeMemberRead[];
};

export type InitiativeMember = InitiativeMemberRead;

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

export type Comment = CommentRead;

/** Tag with required color field */
export type Tag = Omit<TagRead, "color"> & { color: string };

export type ProjectTaskStatus = TaskStatusRead;
export type TaskSubtask = SubtaskRead;
export type TaskAssignee = TaskAssigneeSummary;

/** Project with required permissions array */
export type Project = Omit<ProjectRead, "permissions"> & {
  permissions: ProjectPermissionRead[];
};

/** ProjectTaskSummary with required fields */
export type ProjectTaskSummary = Required<GenProjectTaskSummary>;

/**
 * DeletionEligibilityResponse — the codebase's admin dialog uses the admin variant
 * which includes guild_blockers and initiative_blockers.
 */
export type DeletionEligibilityResponse = AdminDeletionEligibilityResponse;

/** Backward compat alias */
export type ProjectDocumentLink = ProjectDocumentSummary;

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

export interface CommentWithReplies extends CommentRead {
  replies: CommentWithReplies[];
}
