import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  readTaskApiV1TasksTaskIdGet,
  getReadTaskApiV1TasksTaskIdGetQueryKey,
} from "@/api/generated/tasks/tasks";
import {
  listUsersApiV1UsersGet,
  getListUsersApiV1UsersGetQueryKey,
} from "@/api/generated/users/users";
import {
  listCommentsApiV1CommentsGet,
  getListCommentsApiV1CommentsGetQueryKey,
} from "@/api/generated/comments/comments";
import {
  readProjectApiV1ProjectsProjectIdGet,
  getReadProjectApiV1ProjectsProjectIdGetQueryKey,
} from "@/api/generated/projects/projects";
import {
  listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet,
  getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey,
} from "@/api/generated/task-statuses/task-statuses";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/tasks_/$taskId")({
  loader: async ({ context, params }) => {
    const taskId = Number(params.taskId);
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      // Prefetch task, users, and comments in parallel
      const [task] = await Promise.all([
        queryClient.ensureQueryData({
          queryKey: getReadTaskApiV1TasksTaskIdGetQueryKey(taskId),
          queryFn: () => readTaskApiV1TasksTaskIdGet(taskId),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListUsersApiV1UsersGetQueryKey(),
          queryFn: () => listUsersApiV1UsersGet(),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListCommentsApiV1CommentsGetQueryKey({ task_id: taskId }),
          queryFn: () => listCommentsApiV1CommentsGet({ task_id: taskId }),
          staleTime: 30_000,
        }),
      ]);

      // Prefetch project-related data if we have task
      const taskData = task as unknown as { project_id?: number } | undefined;
      if (taskData?.project_id) {
        await Promise.all([
          queryClient.ensureQueryData({
            queryKey: getReadProjectApiV1ProjectsProjectIdGetQueryKey(taskData.project_id),
            queryFn: () => readProjectApiV1ProjectsProjectIdGet(taskData.project_id!),
            staleTime: 30_000,
          }),
          queryClient.ensureQueryData({
            queryKey: getListTaskStatusesApiV1ProjectsProjectIdTaskStatusesGetQueryKey(
              taskData.project_id
            ),
            queryFn: () =>
              listTaskStatusesApiV1ProjectsProjectIdTaskStatusesGet(taskData.project_id!),
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
