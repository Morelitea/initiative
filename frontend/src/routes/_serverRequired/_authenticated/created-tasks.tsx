import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { apiClient } from "@/api/client";
import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { getItem } from "@/lib/storage";

type CreatedTasksSearchParams = {
  page?: number;
};

const STORAGE_KEY = "initiative-created-tasks-filters";
const PAGE_SIZE = 20;

type Filters = {
  statusFilters: unknown[];
  priorityFilters: unknown[];
  guildFilters: unknown[];
};

const DEFAULT_FILTERS: Filters = {
  statusFilters: [],
  priorityFilters: [],
  guildFilters: [],
};

function sanitize(value: unknown): Filters {
  if (value === null || typeof value !== "object") return DEFAULT_FILTERS;
  const v = value as Partial<Filters>;
  return {
    statusFilters: Array.isArray(v.statusFilters) ? v.statusFilters : [],
    priorityFilters: Array.isArray(v.priorityFilters) ? v.priorityFilters : [],
    guildFilters: Array.isArray(v.guildFilters) ? v.guildFilters : [],
  };
}

function readPrefetchFilters(queryClient: {
  getQueryData: <T>(key: readonly unknown[]) => T | undefined;
}): Filters {
  const fromCache = queryClient.getQueryData<UserViewPreferencesMap>(VIEW_PREFERENCES_QUERY_KEY)
    ?.items?.[STORAGE_KEY];
  if (fromCache !== undefined) return sanitize(fromCache);
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_FILTERS;
    return sanitize(JSON.parse(raw));
  } catch {
    return DEFAULT_FILTERS;
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
    const { statusFilters, priorityFilters, guildFilters } = readPrefetchFilters(queryClient);

    const conditions: Array<{ field: string; op: string; value: unknown }> = [];
    if (statusFilters.length > 0)
      conditions.push({ field: "status_category", op: "in_", value: statusFilters });
    if (priorityFilters.length > 0)
      conditions.push({ field: "priority", op: "in_", value: priorityFilters });
    if (guildFilters.length > 0)
      conditions.push({ field: "guild_id", op: "in_", value: guildFilters });

    const defaultSorting = [
      { field: "date_group", dir: "asc" },
      { field: "due_date", dir: "asc" },
    ];
    const params: Record<string, string | number> = {
      page: 1,
      page_size: PAGE_SIZE,
      sorting: JSON.stringify(defaultSorting),
    };
    if (conditions.length > 0) params.conditions = JSON.stringify(conditions);

    try {
      await queryClient.ensureQueryData({
        queryKey: [
          "tasks",
          "me",
          "created",
          statusFilters,
          priorityFilters,
          guildFilters,
          1,
          PAGE_SIZE,
          "date_group+due_date",
        ],
        queryFn: () => apiClient.get("/me/tasks/created", { params }).then((r) => r.data),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyCreatedTasksPage").then((m) => ({ default: m.MyCreatedTasksPage }))
  ),
});
