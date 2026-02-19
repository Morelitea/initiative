import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { getItem } from "@/lib/storage";

type MyTasksSearchParams = {
  page?: number;
  authenticated?: string;
};

const STORAGE_KEY = "initiative-my-tasks-filters";
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

export const Route = createFileRoute("/_serverRequired/_authenticated/")({
  validateSearch: (search: Record<string, unknown>): MyTasksSearchParams => ({
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
    authenticated: typeof search.authenticated === "string" ? search.authenticated : undefined,
  }),
  loader: async ({ context }) => {
    const { queryClient } = context;
    const { statusFilters, priorityFilters, guildFilters } = readStoredFilters();

    const params: Record<string, string | string[] | number | number[]> = {
      scope: "global",
      page: 1,
      page_size: PAGE_SIZE,
      sort_by: "date_group,due_date",
      sort_dir: "asc,asc",
    };
    if (statusFilters.length > 0) params.status_category = statusFilters;
    if (priorityFilters.length > 0) params.priorities = priorityFilters;
    if (guildFilters.length > 0) params.guild_ids = guildFilters;

    try {
      await queryClient.ensureQueryData({
        queryKey: [
          "tasks",
          "global",
          "global",
          statusFilters,
          priorityFilters,
          guildFilters,
          1,
          PAGE_SIZE,
          "date_group,due_date",
          "asc,asc",
        ],
        queryFn: () => apiClient.get("/tasks/", { params }).then((r) => r.data),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/MyTasksPage").then((m) => ({ default: m.MyTasksPage }))
  ),
});
