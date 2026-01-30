import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";

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
  if (typeof window === "undefined") return defaults;
  try {
    const raw = localStorage.getItem(`project:${projectId}:view-filters`);
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

export const Route = createFileRoute("/_serverRequired/_authenticated/projects_/$projectId")({
  loader: async ({ context, params }) => {
    const projectId = Number(params.projectId);
    const { queryClient } = context;

    // Read saved filters from localStorage
    const { assigneeFilters, statusFilters, showArchived } = getStoredFilters(projectId);

    // Build task query params
    const taskParams: Record<string, number | string[] | number[] | boolean> = {
      project_id: projectId,
    };
    if (assigneeFilters.length > 0) taskParams.assignee_ids = assigneeFilters;
    if (statusFilters.length > 0) taskParams.task_status_ids = statusFilters;
    if (showArchived) taskParams.include_archived = true;

    // Prefetch in background - don't block navigation on failure
    try {
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
        queryClient.ensureQueryData({
          queryKey: ["tasks", projectId, assigneeFilters, statusFilters, showArchived],
          queryFn: () => apiClient.get("/tasks/", { params: taskParams }).then((r) => r.data),
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
