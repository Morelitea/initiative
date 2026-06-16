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
import {
  getListUsersApiV1GGuildIdUsersGetQueryKey,
  listUsersApiV1GGuildIdUsersGet,
} from "@/api/generated/users/users";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/tasks_/$taskId")({
  loader: async ({ context, params }) => {
    const taskId = Number(params.taskId);
    const guildId = Number(params.guildId);
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      // Prefetch task, users, and comments in parallel
      const [task] = await Promise.all([
        queryClient.ensureQueryData({
          queryKey: getReadTaskApiV1GGuildIdTasksTaskIdGetQueryKey(guildId, taskId),
          queryFn: () => readTaskApiV1GGuildIdTasksTaskIdGet(guildId, taskId),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListUsersApiV1GGuildIdUsersGetQueryKey(guildId),
          queryFn: () => listUsersApiV1GGuildIdUsersGet(guildId),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListCommentsApiV1GGuildIdCommentsGetQueryKey(guildId, { task_id: taskId }),
          queryFn: () => listCommentsApiV1GGuildIdCommentsGet(guildId, { task_id: taskId }),
          staleTime: 30_000,
        }),
      ]);

      // Prefetch project-related data if we have task
      const taskData = task as unknown as { project_id?: number } | undefined;
      if (taskData?.project_id) {
        await Promise.all([
          queryClient.ensureQueryData({
            queryKey: getReadProjectApiV1GGuildIdProjectsProjectIdGetQueryKey(
              guildId,
              taskData.project_id
            ),
            queryFn: () =>
              readProjectApiV1GGuildIdProjectsProjectIdGet(guildId, taskData.project_id!),
            staleTime: 30_000,
          }),
          queryClient.ensureQueryData({
            queryKey: getListTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGetQueryKey(
              guildId,
              taskData.project_id
            ),
            queryFn: () =>
              listTaskStatusesApiV1GGuildIdProjectsProjectIdTaskStatusesGet(
                guildId,
                taskData.project_id!
              ),
            staleTime: 60_000,
          }),
        ]);
      }
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/TaskEditPage").then((m) => ({ default: m.TaskEditPage }))
  ),
});
