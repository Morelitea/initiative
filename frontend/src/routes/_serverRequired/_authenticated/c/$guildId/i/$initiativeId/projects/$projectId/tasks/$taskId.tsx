import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getListCommentsApiV1GGuildIdCommentsGetQueryKey,
  listCommentsApiV1GGuildIdCommentsGet,
} from "@/api/generated/comments/comments";
import {
  getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey,
  readProjectApiV1GGuildIdProjectsProjectIdGet,
} from "@/api/generated/projects/projects";
import {
  getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey,
  listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet,
} from "@/api/generated/task-statuses/task-statuses";
import {
  getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey,
  readTaskApiV1GGuildIdTasksTaskIdGet,
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
        queryKey: getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey(guildId, taskId),
        queryFn: () => readTaskApiV1GGuildIdTasksTaskIdGet(guildId, taskId),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getListCommentsApiV1GGuildIdCommentsGetQueryKey(guildId, { task_id: taskId }),
        queryFn: () => listCommentsApiV1GGuildIdCommentsGet(guildId, { task_id: taskId }),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(guildId, projectId),
        queryFn: () => readProjectApiV1GGuildIdProjectsProjectIdGet(guildId, projectId),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey(
          guildId,
          projectId
        ),
        queryFn: () =>
          listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet(guildId, projectId),
        staleTime: 60_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/TaskEditPage").then((m) => ({ default: m.TaskEditPage }))
  ),
});
