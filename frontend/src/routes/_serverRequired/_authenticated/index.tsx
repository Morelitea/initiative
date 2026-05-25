import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { apiClient } from "@/api/client";
import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { getItem } from "@/lib/storage";

type MyTasksSearchParams = {
  page?: number;
  authenticated?: string;
};

const STORAGE_KEY = "initiative-my-tasks-filters";
const PAGE_SIZE = 20;

type MyTasksFilters = {
  statusFilters: unknown[];
  priorityFilters: unknown[];
  guildFilters: unknown[];
};

const DEFAULT_FILTERS: MyTasksFilters = {
  statusFilters: [],
  priorityFilters: [],
  guildFilters: [],
};

function sanitize(value: unknown): MyTasksFilters {
  if (value === null || typeof value !== "object") return DEFAULT_FILTERS;
  const v = value as Partial<MyTasksFilters>;
  return {
    statusFilters: Array.isArray(v.statusFilters) ? v.statusFilters : [],
    priorityFilters: Array.isArray(v.priorityFilters) ? v.priorityFilters : [],
    guildFilters: Array.isArray(v.guildFilters) ? v.guildFilters : [],
  };
}

/**
 * Route loaders run before any React hook can fetch the view-preferences
 * map, so we read from whatever is closest: the hydrated React Query
 * cache (after the first authenticated render), or the legacy local
 * storage blob (only present during the first session after deploy,
 * before the one-shot migration runs). After both are exhausted, the
 * page component itself will re-fetch with the real persisted filters.
 */
function readPrefetchFilters(queryClient: {
  getQueryData: <T>(key: readonly unknown[]) => T | undefined;
}): MyTasksFilters {
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
      scope: "global",
      page: 1,
      page_size: PAGE_SIZE,
      sorting: JSON.stringify(defaultSorting),
    };
    if (conditions.length > 0) params.conditions = JSON.stringify(conditions);

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
          "date_group+due_date",
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
