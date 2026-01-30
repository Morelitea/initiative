import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";

export const Route = createFileRoute("/_serverRequired/_authenticated/projects_/$projectId")({
  loader: async ({ context, params }) => {
    const projectId = Number(params.projectId);
    const { queryClient } = context;

    await Promise.all([
      queryClient.ensureQueryData({
        queryKey: ["project", projectId],
        queryFn: () => apiClient.get(`/projects/${projectId}`).then((r) => r.data),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: ["projects", projectId, "task-statuses"],
        queryFn: () => apiClient.get(`/projects/${projectId}/task-statuses/`).then((r) => r.data),
        staleTime: 60_000,
      }),
      queryClient.ensureQueryData({
        queryKey: ["users"],
        queryFn: () => apiClient.get("/users/").then((r) => r.data),
        staleTime: 60_000,
      }),
    ]);
  },
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectDetailPage").then((m) => ({ default: m.ProjectDetailPage }))
  ),
});
