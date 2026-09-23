import type {
  TaskAssigneeSummary,
  TaskListRead,
  TaskListResponse,
  TaskStatusRead,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildTaskAssignee(
  overrides: Partial<TaskAssigneeSummary> = {}
): TaskAssigneeSummary {
  counter++;
  return {
    id: counter,
    username: `assignee-${counter}`,
    discriminator: 2000 + counter,
    full_name: `Assignee ${counter}`,
    avatar_url: null,
    status: "active",
    ...overrides,
  };
}

export function buildTask(overrides: Partial<TaskListRead> = {}): TaskListRead {
  counter++;

  const defaultStatus: TaskStatusRead = {
    id: 1,
    project_id: 1,
    name: "To Do",
    category: "todo",
    position: 0,
    is_default: true,
    color: "#94A3B8",
    icon: "circle",
  };

  return {
    id: counter,
    title: `Task ${counter}`,
    description: "",
    task_status_id: 1,
    task_status: defaultStatus,
    priority: "medium",
    project_id: 1,
    assignees: [],
    start_date: null,
    due_date: null,
    recurrence: null,
    recurrence_strategy: "fixed",
    recurrence_occurrence_count: 0,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    position: counter,
    archived_at: null,
    created_by: 1,
    comment_count: 0,
    blocked_by_open_count: 0,
    guild_id: null,
    guild_name: null,
    project_name: null,
    initiative_id: null,
    initiative_name: null,
    initiative_color: null,
    checklist_progress: null,
    completed_at: null,
    tags: [],
    properties: [],
    ...overrides,
  };
}

export function buildTaskListResponse(
  itemsOrOverrides: TaskListRead[] | Partial<TaskListResponse> = {}
): TaskListResponse {
  if (Array.isArray(itemsOrOverrides)) {
    return {
      items: itemsOrOverrides,
      total_count: itemsOrOverrides.length,
      page: 1,
      page_size: 50,
      has_next: false,
      has_prev: false,
      sorting: null,
    };
  }
  return {
    items: [],
    total_count: 0,
    page: 1,
    page_size: 50,
    has_next: false,
    has_prev: false,
    sorting: null,
    ...itemsOrOverrides,
  };
}
