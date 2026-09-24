import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getListCommentsApiV1CGuildIdCommentsGetQueryKey,
  listCommentsApiV1CGuildIdCommentsGet,
} from "@/api/generated/comments/comments";
import {
  getReadProjectApiV1CGuildIdProjectsProjectIdGetQueryKey,
  readProjectApiV1CGuildIdProjectsProjectIdGet,
} from "@/api/generated/projects/projects";
import {
  getListTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGetQueryKey,
  listTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGet,
} from "@/api/generated/task-statuses/task-statuses";
import {
  getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey,
  readTaskApiV1CGuildIdTasksTaskIdGet,
} from "@/api/generated/tasks/tasks";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/projects/$projectId/tasks/$taskId"
)({
  loader: ({ context, params }) => {
    const taskId = Number(params.taskId);
    const projectId = Number(params.projectId);
    const guildId = Number(params.guildId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    // The project comes from the path, so all four reads start together
    // instead of waiting on the task to name its project.
    void Promise.all([
      queryClient.ensureQueryData({
        queryKey: getReadTaskApiV1CGuildIdTasksTaskIdGetQueryKey(guildId, taskId),
        queryFn: () => readTaskApiV1CGuildIdTasksTaskIdGet(guildId, taskId),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getListCommentsApiV1CGuildIdCommentsGetQueryKey(guildId, { task_id: taskId }),
        queryFn: () => listCommentsApiV1CGuildIdCommentsGet(guildId, { task_id: taskId }),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getReadProjectApiV1CGuildIdProjectsProjectIdGetQueryKey(guildId, projectId),
        queryFn: () => readProjectApiV1CGuildIdProjectsProjectIdGet(guildId, projectId),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getListTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGetQueryKey(
          guildId,
          projectId
        ),
        queryFn: () =>
          listTaskStatusesApiV1CGuildIdProjectsProjectIdTaskStatusesGet(guildId, projectId),
        staleTime: 60_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/TaskEditPage").then((m) => ({ default: m.TaskEditPage }))
  ),
});
