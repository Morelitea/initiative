import type {
  ProjectPermissionRead,
  TaskStatusCategory,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";
import type { Project } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildProjectTaskStatus(overrides: Partial<TaskStatusRead> = {}): TaskStatusRead {
  counter++;
  return {
    id: counter,
    project_id: 1,
    name: `Status ${counter}`,
    category: "todo" as TaskStatusCategory,
    position: counter - 1,
    is_default: false,
    ...overrides,
  };
}

/**
 * Returns the four default task statuses that are created for every new project.
 * Accepts a projectId to set the project_id field on each status.
 */
export function buildDefaultTaskStatuses(projectId: number = 1): TaskStatusRead[] {
  const categories: Array<{
    name: string;
    category: TaskStatusCategory;
    isDefault: boolean;
  }> = [
    { name: "Backlog", category: "backlog", isDefault: false },
    { name: "To Do", category: "todo", isDefault: true },
    { name: "In Progress", category: "in_progress", isDefault: false },
    { name: "Done", category: "done", isDefault: false },
  ];

  return categories.map((entry, index) =>
    buildProjectTaskStatus({
      project_id: projectId,
      name: entry.name,
      category: entry.category,
      position: index,
      is_default: entry.isDefault,
    })
  );
}

export function buildProjectPermission(
  overrides: Partial<ProjectPermissionRead> = {}
): ProjectPermissionRead {
  counter++;
  return {
    user_id: counter,
    level: "read",
    created_at: "2026-01-15T00:00:00.000Z",
    project_id: 1,
    ...overrides,
  };
}

export function buildProject(overrides: Partial<Project> = {}): Project {
  counter++;
  return {
    id: counter,
    name: `Project ${counter}`,
    icon: null,
    description: `Description for project ${counter}`,
    owner_id: 1,
    initiative_id: 1,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    is_archived: false,
    is_template: false,
    archived_at: null,
    pinned_at: null,
    owner: undefined,
    initiative: null,
    permissions: [],
    role_permissions: [],
    my_permission_level: "owner",
    sort_order: counter,
    is_favorited: false,
    last_viewed_at: null,
    documents: [],
    task_summary: { total: 0, completed: 0 },
    tags: [],
    ...overrides,
  };
}
