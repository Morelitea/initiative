import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { getItem } from "@/lib/storage";

type CreatedTasksSearchParams = {
  page?: number;
};

const STORAGE_KEY = "initiative-created-tasks-filters";
const PAGE_SIZE = 20;

function readStoredFilters() {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return { statusFilters: [], priorityFilters: [], guildFilters: [] };
    const parsed = JSON.parse(raw);
    return {
      statusFilters: Array.isArray(parsed?.statusFilters) ? parsed.statusFilters : [],
      priorityFilters: Array.isArray(parsed?.priorityFilters) ? parsed.priorityFilters : [],
      guildFilters: Array.isArray(parsed?.guildFilters) ? parsed.guildFilters : [],
    };
  } catch {
    return { statusFilters: [], priorityFilters: [], guildFilters: [] };
  }
}

export const Route = createFileRoute("/_serverRequired/_authenticated/created-tasks")({
  validateSearch: (search: Record<string, unknown>): CreatedTasksSearchParams => ({
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
  }),
  loader: async ({ context }) => {
    const { queryClient } = context;
    const { statusFilters, priorityFilters, guildFilters } = readStoredFilters();

    const conditions: Array<{ field: string; op: string; value: unknown }> = [];
    if (statusFilters.length > 0)
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    if (priorityFilters.length > 0)
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    if (guildFilters.length > 0)
      conditions.push({ field: "guild_id", op: "in_", value: guildFilters });

    const params: Record<string, string | number> = {
      scope: "global_created",
      page: 1,
      page_size: PAGE_SIZE,
      sort_by: "date_group",
      sort_dir: "asc",
    };
    if (conditions.length > 0) params.conditions = JSON.stringify(conditions);

    try {
      await queryClient.ensureQueryData({
        queryKey: [
          "tasks",
          "global",
          "global_created",
          statusFilters,
          priorityFilters,
          guildFilters,
          1,
          PAGE_SIZE,
          "date_group",
          "asc",
        ],
        queryFn: () => apiClient.get("/tasks/", { params }).then((r) => r.data),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/CreatedTasksPage").then((m) => ({ default: m.CreatedTasksPage }))
  ),
});
