export type UserRole = 'admin' | 'project_manager' | 'member';

export interface User {
  id: number;
  email: string;
  full_name?: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  avatar_base64?: string | null;
  avatar_url?: string | null;
}

export type ProjectRole = 'admin' | 'project_manager' | 'member';

export interface ProjectMember {
  user_id: number;
  role: ProjectRole;
  joined_at: string;
}

export interface Team {
  id: number;
  name: string;
  description?: string;
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
  team_id?: number | null;
  created_at: string;
  updated_at: string;
  read_roles: ProjectRole[];
  write_roles: ProjectRole[];
  is_archived: boolean;
  is_template: boolean;
  archived_at?: string | null;
  owner?: User;
  team?: Team | null;
  members: ProjectMember[];
}

export type TaskStatus = 'backlog' | 'in_progress' | 'blocked' | 'done';
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface Task {
  id: number;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  project_id: number;
  assignees: User[];
  due_date?: string;
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

export interface RegistrationSettings {
  auto_approved_domains: string[];
  pending_users: User[];
}
