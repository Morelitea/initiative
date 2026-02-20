import type { TaskListResponse } from "@/api/generated/initiativeAPI.schemas";
import type { Task, TaskAssignee, ProjectTaskStatus } from "@/types/api";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildTaskAssignee(overrides: Partial<TaskAssignee> = {}): TaskAssignee {
  counter++;
  return {
    id: counter,
    full_name: `Assignee ${counter}`,
    avatar_url: null,
    avatar_base64: null,
    ...overrides,
  };
}

export function buildTask(overrides: Partial<Task> = {}): Task {
  counter++;

  const defaultStatus: ProjectTaskStatus = {
    id: 1,
    project_id: 1,
    name: "To Do",
    category: "todo",
    position: 0,
    is_default: true,
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
    start_date: undefined,
    due_date: undefined,
    recurrence: null,
    recurrence_strategy: "fixed",
    recurrence_occurrence_count: 0,
    created_at: "2026-01-15T00:00:00.000Z",
    updated_at: "2026-01-15T00:00:00.000Z",
    sort_order: counter,
    is_archived: false,
    comment_count: 0,
    guild_id: null,
    guild_name: null,
    project_name: null,
    initiative_id: null,
    initiative_name: null,
    initiative_color: null,
    subtask_progress: null,
    tags: [],
    ...overrides,
  };
}

export function buildTaskListResponse(
  itemsOrOverrides: Task[] | Partial<TaskListResponse> = {}
): TaskListResponse {
  if (Array.isArray(itemsOrOverrides)) {
    return {
      items: itemsOrOverrides,
      total_count: itemsOrOverrides.length,
      page: 1,
      page_size: 50,
      has_next: false,
      sort_by: null,
      sort_dir: null,
    };
  }
  return {
    items: [],
    total_count: 0,
    page: 1,
    page_size: 50,
    has_next: false,
    sort_by: null,
    sort_dir: null,
    ...itemsOrOverrides,
  };
}
