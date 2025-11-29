import type { SerializedEditorState } from "lexical";

export type UserRole = "admin" | "member";
export type GuildRole = "admin" | "member";

export type InitiativeRole = "project_manager" | "member";

export interface User {
  id: number;
  active_guild_id?: number | null;
  email: string;
  full_name?: string;
  role: UserRole;
  can_create_guilds?: boolean;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
  avatar_base64?: string | null;
  avatar_url?: string | null;
  show_project_sidebar?: boolean;
  show_project_tabs?: boolean;
  timezone?: string;
  overdue_notification_time?: string;
  notify_initiative_addition?: boolean;
  notify_task_assignment?: boolean;
  notify_project_added?: boolean;
  notify_overdue_tasks?: boolean;
  last_overdue_notification_at?: string | null;
  last_task_assignment_digest_at?: string | null;
  initiative_roles?: UserInitiativeRole[];
}

export interface UserInitiativeRole {
  initiative_id: number;
  initiative_name: string;
  role: InitiativeRole;
}

export type ProjectPermissionLevel = "owner" | "write";

export interface ProjectPermission {
  user_id: number;
  level: ProjectPermissionLevel;
  created_at: string;
  project_id?: number;
}

export interface Initiative {
  id: number;
  name: string;
  description?: string;
  color?: string | null;
  is_default?: boolean;
  created_at: string;
  updated_at: string;
  members: InitiativeMember[];
}

export interface InitiativeMember {
  user: User;
  role: InitiativeRole;
  joined_at: string;
}

export interface DocumentProjectLink {
  project_id: number;
  project_name?: string | null;
  project_icon?: string | null;
  attached_at: string;
}

export interface DocumentSummary {
  id: number;
  initiative_id: number;
  title: string;
  featured_image_url?: string | null;
  is_template: boolean;
  created_by_id: number;
  updated_by_id: number;
  created_at: string;
  updated_at: string;
  initiative?: Initiative | null;
  projects: DocumentProjectLink[];
  comment_count?: number;
}

export interface DocumentRead extends DocumentSummary {
  content: SerializedEditorState;
  write_member_ids: number[];
}

export interface DocumentDuplicateRequest {
  title?: string;
}

export interface DocumentCopyRequest {
  target_initiative_id: number;
  title?: string;
}

export interface ProjectDocumentLink {
  document_id: number;
  title: string;
  updated_at: string;
  attached_at: string;
}

export interface Guild {
  id: number;
  name: string;
  description?: string | null;
  icon_base64?: string | null;
  role: GuildRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface GuildInviteStatus {
  code: string;
  guild_id?: number | null;
  guild_name?: string | null;
  is_valid: boolean;
  reason?: string | null;
  expires_at?: string | null;
  max_uses?: number | null;
  uses?: number | null;
}

export interface GuildInviteRead {
  id: number;
  code: string;
  guild_id: number;
  created_by_user_id?: number | null;
  expires_at?: string | null;
  max_uses?: number | null;
  uses: number;
  invitee_email?: string | null;
  created_at: string;
}

export interface Project {
  id: number;
  name: string;
  icon?: string | null;
  description?: string;
  members_can_write: boolean;
  owner_id: number;
  initiative_id: number;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  is_template: boolean;
  archived_at?: string | null;
  owner?: User;
  initiative?: Initiative | null;
  permissions: ProjectPermission[];
  sort_order?: number | null;
  is_favorited?: boolean;
  last_viewed_at?: string | null;
  documents?: ProjectDocumentLink[];
}

export interface AttachmentUploadResponse {
  filename: string;
  url: string;
  content_type: string;
  size: number;
}

export type TaskStatus = "backlog" | "in_progress" | "blocked" | "done";
export type TaskPriority = "low" | "medium" | "high" | "urgent";
export type TaskRecurrenceFrequency = "daily" | "weekly" | "monthly" | "yearly";
export type TaskRecurrenceEnds = "never" | "on_date" | "after_occurrences";
export type TaskRecurrenceMonthlyMode = "day_of_month" | "weekday";
export type TaskWeekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";
export type TaskWeekPosition = "first" | "second" | "third" | "fourth" | "last";

export interface TaskRecurrence {
  frequency: TaskRecurrenceFrequency;
  interval: number;
  weekdays: TaskWeekday[];
  monthly_mode: TaskRecurrenceMonthlyMode;
  day_of_month?: number | null;
  month?: number | null;
  weekday_position?: TaskWeekPosition | null;
  weekday?: TaskWeekday | null;
  ends: TaskRecurrenceEnds;
  end_after_occurrences?: number | null;
  end_date?: string | null;
}

export interface Task {
  id: number;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  project_id: number;
  assignees: User[];
  start_date?: string;
  due_date?: string;
  recurrence?: TaskRecurrence | null;
  recurrence_occurrence_count?: number;
  created_at: string;
  updated_at: string;
  sort_order: number;
  comment_count?: number;
}

export interface CommentAuthor {
  id: number;
  email: string;
  full_name?: string | null;
  avatar_url?: string | null;
  avatar_base64?: string | null;
}

export interface Comment {
  id: number;
  content: string;
  author_id: number;
  task_id?: number | null;
  document_id?: number | null;
  parent_comment_id?: number | null;
  created_at: string;
  author?: CommentAuthor | null;
}

export interface ProjectActivityEntry {
  comment_id: number;
  content: string;
  created_at: string;
  author?: CommentAuthor | null;
  task_id: number;
  task_title: string;
}

export interface ProjectActivityResponse {
  items: ProjectActivityEntry[];
  next_page?: number | null;
  project_id?: number;
}

export interface TaskReorderPayload {
  project_id: number;
  items: {
    id: number;
    status: TaskStatus;
    sort_order: number;
  }[];
}

export interface ProjectReorderPayload {
  project_ids: number[];
}

export interface ApiKeyMetadata {
  id: number;
  name: string;
  token_prefix: string;
  is_active: boolean;
  created_at: string;
  last_used_at?: string | null;
  expires_at?: string | null;
}

export interface ApiKeyListResponse {
  keys: ApiKeyMetadata[];
}

export interface ApiKeyCreateResponse {
  api_key: ApiKeyMetadata;
  secret: string;
}

export interface RoleLabels {
  admin: string;
  project_manager: string;
  member: string;
}

export interface EmailSettings {
  host?: string | null;
  port?: number | null;
  secure: boolean;
  reject_unauthorized: boolean;
  username?: string | null;
  has_password: boolean;
  from_address?: string | null;
  test_recipient?: string | null;
}

export type NotificationType =
  | "task_assignment"
  | "initiative_added"
  | "project_added"
  | "user_pending_approval";

export interface Notification {
  id: number;
  type: NotificationType;
  data: Record<string, unknown>;
  created_at: string;
  read_at?: string | null;
}

export interface NotificationListResponse {
  notifications: Notification[];
  unread_count: number;
}

export interface NotificationCountResponse {
  unread_count: number;
}
