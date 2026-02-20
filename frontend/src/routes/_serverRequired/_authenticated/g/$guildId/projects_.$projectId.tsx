import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { getItem } from "@/lib/storage";

import {
  readProjectApiV1ProjectsProjectIdGet,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
} from "@/api/generated/projects/projects";
import {
  listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet,
  getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey,
} from "@/api/generated/task-statuses/task-statuses";
import {
  listUsersApiV1UsersGet,
  getListUsersApiV1UsersGetQueryKey,
} from "@/api/generated/users/users";
import {
  listTasksApiV1TasksGet,
  getListTasksApiV1TasksGetQueryKey,
} from "@/api/generated/tasks/tasks";

type StoredFilters = {
  viewMode: string;
  assigneeFilters: string[];
  dueFilter: string;
  statusFilters: number[];
  showArchived: boolean;
};

function getStoredFilters(projectId: number): {
  assigneeFilters: string[];
  statusFilters: number[];
  showArchived: boolean;
} {
  const defaults = {
    assigneeFilters: [] as string[],
    statusFilters: [] as number[],
    showArchived: false,
  };
  try {
    const raw = getItem(`project:${projectId}:view-filters`);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<StoredFilters>;
    return {
      assigneeFilters: Array.isArray(parsed.assigneeFilters) ? parsed.assigneeFilters : [],
      statusFilters: Array.isArray(parsed.statusFilters) ? parsed.statusFilters : [],
      showArchived: typeof parsed.showArchived === "boolean" ? parsed.showArchived : false,
    };
  } catch {
    return defaults;
  }
}

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/projects_/$projectId"
)({
  loader: async ({ context, params }) => {
    const projectId = Number(params.projectId);
    const { queryClient } = context;

    // Read saved filters from storage
    const { assigneeFilters, statusFilters, showArchived } = getStoredFilters(projectId);

    // Build task query params (page_size=0 fetches all for drag-and-drop)
    const taskParams: Record<string, number | string[] | number[] | boolean> = {
      project_id: projectId,
      page_size: 0,
    };
    if (assigneeFilters.length > 0) taskParams.assignee_ids = assigneeFilters;
    if (statusFilters.length > 0) taskParams.task_status_ids = statusFilters;
    if (showArchived) taskParams.include_archived = true;

    // Prefetch in background - don't block navigation on failure
    try {
      await Promise.all([
        queryClient.ensureQueryData({
          queryKey: getReadProjectApiV1ProjectsProjectIdGetQueryKey(projectId),
          queryFn: () => readProjectApiV1ProjectsProjectIdGet(projectId),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey(projectId),
          queryFn: () => listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(projectId),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListUsersApiV1UsersGetQueryKey(),
          queryFn: () => listUsersApiV1UsersGet(),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListTasksApiV1TasksGetQueryKey(taskParams),
          queryFn: () => listTasksApiV1TasksGet(taskParams),
          staleTime: 30_000,
        }),
      ]);
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectDetailPage").then((m) => ({ default: m.ProjectDetailPage }))
  ),
});
