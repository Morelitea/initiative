import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";

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
          queryKey: ["task", taskId],
          queryFn: () => apiClient.get(`/tasks/${taskId}`).then((r) => r.data),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData({
          queryKey: ["users", { guildId }],
          queryFn: () => apiClient.get("/users/").then((r) => r.data),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: ["comments", "task", taskId],
          queryFn: () =>
            apiClient.get("/comments/", { params: { task_id: taskId } }).then((r) => r.data),
          staleTime: 30_000,
        }),
      ]);

      // Prefetch project-related data if we have task
      if (task?.project_id) {
        await Promise.all([
          queryClient.ensureQueryData({
            queryKey: ["project", task.project_id],
            queryFn: () => apiClient.get(`/projects/${task.project_id}`).then((r) => r.data),
            staleTime: 30_000,
          }),
          queryClient.ensureQueryData({
            queryKey: ["projects", task.project_id, "task-statuses"],
            queryFn: () =>
              apiClient.get(`/projects/${task.project_id}/task-statuses/`).then((r) => r.data),
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
