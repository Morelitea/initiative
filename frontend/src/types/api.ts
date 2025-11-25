export type UserRole = "admin" | "project_manager" | "member";

export interface User {
  id: number;
  email: string;
  full_name?: string;
  role: UserRole;
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
}

export type ProjectRole = "admin" | "project_manager" | "member";

export interface ProjectMember {
  user_id: number;
  role: ProjectRole;
  joined_at: string;
}

export interface Initiative {
  id: number;
  name: string;
  description?: string;
  color?: string | null;
  created_at: string;
  updated_at: string;
  members: User[];
}

export interface Project {
  id: number;
  name: string;
  icon?: string | null;
  description?: string;
  owner_id: number;
  initiative_id?: number | null;
  created_at: string;
  updated_at: string;
  read_roles: ProjectRole[];
  write_roles: ProjectRole[];
  is_archived: boolean;
  is_template: boolean;
  archived_at?: string | null;
  owner?: User;
  initiative?: Initiative | null;
  members: ProjectMember[];
  sort_order?: number | null;
  is_favorited?: boolean;
  last_viewed_at?: string | null;
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

export interface RegistrationSettings {
  auto_approved_domains: string[];
  pending_users: User[];
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
