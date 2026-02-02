import type { SerializedEditorState } from "lexical";

export type UserRole = "admin" | "member";
export type GuildRole = "admin" | "member";

export type InitiativeRole = "project_manager" | "member";

export interface UserPublic {
  id: number;
  email: string;
  full_name?: string;
  avatar_base64?: string | null;
  avatar_url?: string | null;
}

export interface UserGuildMember extends UserPublic {
  role: UserRole;
  guild_role?: GuildRole;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  initiative_roles?: UserInitiativeRole[];
}

export interface User extends UserPublic {
  active_guild_id?: number | null;
  role: UserRole;
  can_create_guilds?: boolean;
  is_active: boolean;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
  week_starts_on?: number;
  timezone?: string;
  overdue_notification_time?: string;
  notify_initiative_addition?: boolean;
  notify_task_assignment?: boolean;
  notify_project_added?: boolean;
  notify_overdue_tasks?: boolean;
  notify_mentions?: boolean;
  last_overdue_notification_at?: string | null;
  last_task_assignment_digest_at?: string | null;
  color_theme?: string;
  initiative_roles?: UserInitiativeRole[];
}

export interface UserInitiativeRole {
  initiative_id: number;
  initiative_name: string;
  role: InitiativeRole;
}

export type ProjectPermissionLevel = "owner" | "write" | "read";

export interface ProjectPermission {
  user_id: number;
  level: ProjectPermissionLevel;
  created_at: string;
  project_id?: number;
}

export type DocumentPermissionLevel = "owner" | "write" | "read";

export interface DocumentPermission {
  user_id: number;
  level: DocumentPermissionLevel;
  created_at: string;
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
  user: UserPublic;
  role: InitiativeRole;
  joined_at: string;
}

export interface DocumentProjectLink {
  project_id: number;
  project_name?: string | null;
  project_icon?: string | null;
  attached_at: string;
}

export type DocumentType = "native" | "file";

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
  permissions?: DocumentPermission[];
  // File document fields
  document_type?: DocumentType;
  file_url?: string | null;
  file_content_type?: string | null;
  file_size?: number | null;
  original_filename?: string | null;
}

export interface DocumentRead extends DocumentSummary {
  content: SerializedEditorState;
  permissions: DocumentPermission[];
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
  position: number;
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

export interface LeaveGuildEligibilityResponse {
  can_leave: boolean;
  is_last_admin: boolean;
  sole_pm_initiatives: string[];
}

export interface Project {
  id: number;
  name: string;
  icon?: string | null;
  description?: string;
  owner_id: number;
  initiative_id: number;
  created_at: string;
  updated_at: string;
  is_archived: boolean;
  is_template: boolean;
  archived_at?: string | null;
  pinned_at?: string | null;
  owner?: UserPublic;
  initiative?: Initiative | null;
  permissions: ProjectPermission[];
  sort_order?: number | null;
  is_favorited?: boolean;
  last_viewed_at?: string | null;
  documents?: ProjectDocumentLink[];
  task_summary?: ProjectTaskSummary;
}

export interface AttachmentUploadResponse {
  filename: string;
  url: string;
  content_type: string;
  size: number;
}

export type TaskStatusCategory = "backlog" | "todo" | "in_progress" | "done";
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
export type TaskRecurrenceStrategy = "fixed" | "rolling";

export interface ProjectTaskStatus {
  id: number;
  project_id: number;
  name: string;
  category: TaskStatusCategory;
  position: number;
  is_default: boolean;
}

export interface ProjectTaskSummary {
  total: number;
  completed: number;
}

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

export interface TaskProjectInitiativeSummary {
  id: number;
  name: string;
  color?: string | null;
}

export interface TaskProjectSummary {
  id: number;
  name: string;
  icon?: string | null;
  initiative_id?: number | null;
  initiative?: TaskProjectInitiativeSummary | null;
  is_archived?: boolean | null;
  is_template?: boolean | null;
}

export interface TaskGuildSummary {
  id: number;
  name: string;
  icon_base64?: string | null;
}

export interface TaskSubtaskProgress {
  completed: number;
  total: number;
}

export interface TaskSubtask {
  id: number;
  task_id: number;
  content: string;
  is_completed: boolean;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface TaskAssignee {
  id: number;
  full_name?: string | null;
  avatar_url?: string | null;
  avatar_base64?: string | null;
}

export interface Task {
  id: number;
  title: string;
  description?: string;
  task_status_id: number;
  task_status: ProjectTaskStatus;
  priority: TaskPriority;
  project_id: number;
  assignees: TaskAssignee[];
  start_date?: string;
  due_date?: string;
  recurrence?: TaskRecurrence | null;
  recurrence_strategy?: TaskRecurrenceStrategy;
  recurrence_occurrence_count?: number;
  created_at: string;
  updated_at: string;
  sort_order: number;
  is_archived: boolean;
  comment_count?: number;
  guild_id?: number | null;
  guild_name?: string | null;
  project_name?: string | null;
  initiative_id?: number | null;
  initiative_name?: string | null;
  initiative_color?: string | null;
  subtask_progress?: TaskSubtaskProgress | null;
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

export interface CommentWithReplies extends Comment {
  replies: CommentWithReplies[];
}

export type MentionEntityType = "user" | "task" | "doc" | "project";

export interface MentionSuggestion {
  type: MentionEntityType;
  id: number;
  display_text: string;
  subtitle?: string | null;
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
    task_status_id: number;
    sort_order: number;
  }[];
}

export interface TaskMovePayload {
  target_project_id: number;
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

export interface DeviceTokenInfo {
  id: number;
  device_name: string | null;
  created_at: string;
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
  | "user_pending_approval"
  | "mention"
  | "comment_on_task"
  | "comment_on_document"
  | "comment_reply";

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

export interface VelocityWeekData {
  week_start: string;
  assigned: number;
  completed: number;
}

export interface HeatmapDayData {
  date: string;
  activity_count: number;
}

export interface GuildTaskBreakdown {
  guild_id: number;
  guild_name: string;
  completed_count: number;
}

export interface UserStatsResponse {
  streak: number;
  on_time_rate: number;
  avg_completion_days: number | null;
  tasks_completed_total: number;
  tasks_completed_this_week: number;
  backlog_trend: "Growing" | "Shrinking";
  velocity_data: VelocityWeekData[];
  heatmap_data: HeatmapDayData[];
  guild_breakdown: GuildTaskBreakdown[];
}

// AI Settings types
export type AIProvider = "openai" | "anthropic" | "ollama" | "custom";

export interface PlatformAISettings {
  enabled: boolean;
  provider?: AIProvider | null;
  has_api_key: boolean;
  base_url?: string | null;
  model?: string | null;
  allow_guild_override: boolean;
  allow_user_override: boolean;
}

export interface PlatformAISettingsUpdate {
  enabled: boolean;
  provider?: AIProvider | null;
  api_key?: string | null;
  base_url?: string | null;
  model?: string | null;
  allow_guild_override: boolean;
  allow_user_override: boolean;
}

export interface GuildAISettings {
  enabled?: boolean | null;
  provider?: AIProvider | null;
  has_api_key: boolean;
  base_url?: string | null;
  model?: string | null;
  allow_user_override?: boolean | null;
  effective_enabled: boolean;
  effective_provider?: AIProvider | null;
  effective_base_url?: string | null;
  effective_model?: string | null;
  effective_allow_user_override: boolean;
  can_override: boolean;
}

export interface GuildAISettingsUpdate {
  enabled?: boolean | null;
  provider?: AIProvider | null;
  api_key?: string | null;
  base_url?: string | null;
  model?: string | null;
  allow_user_override?: boolean | null;
  clear_settings?: boolean;
}

export interface UserAISettings {
  enabled?: boolean | null;
  provider?: AIProvider | null;
  has_api_key: boolean;
  base_url?: string | null;
  model?: string | null;
  effective_enabled: boolean;
  effective_provider?: AIProvider | null;
  effective_base_url?: string | null;
  effective_model?: string | null;
  can_override: boolean;
  settings_source: "platform" | "guild" | "user" | "mixed";
}

export interface UserAISettingsUpdate {
  enabled?: boolean | null;
  provider?: AIProvider | null;
  api_key?: string | null;
  base_url?: string | null;
  model?: string | null;
  clear_settings?: boolean;
}

export interface ResolvedAISettings {
  enabled: boolean;
  provider?: AIProvider | null;
  has_api_key: boolean;
  base_url?: string | null;
  model?: string | null;
  source: "platform" | "guild" | "user";
}

export interface AITestConnectionRequest {
  provider: AIProvider;
  api_key?: string | null;
  base_url?: string | null;
  model?: string | null;
}

export interface AITestConnectionResponse {
  success: boolean;
  message: string;
  available_models?: string[] | null;
}

export interface AIModelsRequest {
  provider: AIProvider;
  api_key?: string | null;
  base_url?: string | null;
}

export interface AIModelsResponse {
  models: string[];
  error?: string | null;
}

// AI Generation types
export interface GenerateSubtasksResponse {
  subtasks: string[];
}

export interface GenerateDescriptionResponse {
  description: string;
}

// Admin deletion types
export interface ProjectBasic {
  id: number;
  name: string;
  initiative_id: number;
}

export interface GuildBlockerInfo {
  guild_id: number;
  guild_name: string;
  other_members: UserPublic[];
}

export interface InitiativeBlockerInfo {
  initiative_id: number;
  initiative_name: string;
  guild_id: number;
  other_members: UserPublic[];
}

export interface DeletionEligibilityResponse {
  can_delete: boolean;
  blockers: string[];
  warnings: string[];
  owned_projects: ProjectBasic[];
  guild_blockers: GuildBlockerInfo[];
  initiative_blockers: InitiativeBlockerInfo[];
}

export interface AdminUserDeleteRequest {
  deletion_type: "soft" | "hard";
  project_transfers?: Record<number, number>;
}

export interface AccountDeletionResponse {
  success: boolean;
  deletion_type: string;
  message: string;
}

export interface AdminGuildRoleUpdate {
  role: GuildRole;
}

export interface AdminInitiativeRoleUpdate {
  role: InitiativeRole;
}
