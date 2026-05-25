import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import {
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
  readProjectApiV1ProjectsProjectIdGet,
} from "@/api/generated/projects/projects";
import {
  getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey,
  listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet,
} from "@/api/generated/task-statuses/task-statuses";
import {
  getListTasksApiV1TasksGetQueryKey,
  listTasksApiV1TasksGet,
} from "@/api/generated/tasks/tasks";
import {
  getListUsersApiV1UsersGetQueryKey,
  listUsersApiV1UsersGet,
} from "@/api/generated/users/users";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { getItem } from "@/lib/storage";

type StoredFilters = {
  viewMode: string;
  assigneeFilters: string[];
  dueFilter: string;
  statusFilters: number[];
  showArchived: boolean;
};

function sanitize(value: unknown) {
  const defaults = {
    assigneeFilters: [] as string[],
    statusFilters: [] as number[],
    showArchived: false,
  };
  if (value === null || typeof value !== "object") return defaults;
  const parsed = value as Partial<StoredFilters>;
  return {
    assigneeFilters: Array.isArray(parsed.assigneeFilters) ? parsed.assigneeFilters : [],
    statusFilters: Array.isArray(parsed.statusFilters) ? parsed.statusFilters : [],
    showArchived: typeof parsed.showArchived === "boolean" ? parsed.showArchived : false,
  };
}

function getStoredFilters(
  queryClient: { getQueryData: <T>(key: readonly unknown[]) => T | undefined },
  projectId: number
) {
  const scopeKey = `project:${projectId}:view-filters`;
  const fromCache = queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)
    ?.items?.[scopeKey];
  if (fromCache !== undefined) return sanitize(fromCache);
  try {
    const raw = getItem(scopeKey);
    if (!raw) return sanitize(null);
    return sanitize(JSON.parse(raw));
  } catch {
    return sanitize(null);
  }
}

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/projects_/$projectId"
)({
  validateSearch: (search: Record<string, unknown>) => ({
    create: typeof search.create === "string" ? search.create : undefined,
  }),
  loader: async ({ context, params }) => {
    const projectId = Number(params.projectId);
    const { queryClient } = context;

    // Read saved filters from the hydrated view-preferences cache (or
    // legacy localStorage if the user hasn't migrated yet).
    const { assigneeFilters, statusFilters, showArchived } = getStoredFilters(
      queryClient,
      projectId
    );

    // Build task query params (page_size=0 fetches all for drag-and-drop)
    const conditions: Array<{ field: string; op: string; value: unknown }> = [
      { field: "project_id", op: "eq", value: projectId },
    ];
    if (assigneeFilters.length > 0)
      conditions.push({ field: "assignee_ids", op: "in_", value: assigneeFilters });
    if (statusFilters.length > 0)
      conditions.push({ field: "task_status_id", op: "in_", value: statusFilters });

    const taskParams: Record<string, number | string | boolean> = {
      page_size: 0,
      conditions: JSON.stringify(conditions),
    };
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
