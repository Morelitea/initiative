import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { apiClient } from "@/api/client";
import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import { VIEW_PREFERENCES_QUERY_KEY } from "@/hooks/useViewPreference";
import { getItem } from "@/lib/storage";

type MyDocumentsSearchParams = {
  page?: number;
};

const STORAGE_KEY = "initiative-my-documents-filters";
const PAGE_SIZE = 20;

type Filters = { guildFilters: number[] };
const DEFAULT_FILTERS: Filters = { guildFilters: [] };

function sanitize(value: unknown): Filters {
  if (value === null || typeof value !== "object") return DEFAULT_FILTERS;
  const v = value as Partial<Filters>;
  return {
    guildFilters: Array.isArray(v.guildFilters)
      ? v.guildFilters.filter((x): x is number => typeof x === "number")
      : [],
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

export const Route = createFileRoute("/_serverRequired/_authenticated/my-documents")({
  validateSearch: (search: Record<string, unknown>): MyDocumentsSearchParams => ({
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
  }),
  loader: async ({ context }) => {
    const { queryClient } = context;
    const { guildFilters } = readPrefetchFilters(queryClient);

    const params: Record<string, string | string[] | number | number[]> = {
      scope: "global",
      page: 1,
      page_size: PAGE_SIZE,
    };
    if (guildFilters.length > 0) params.guild_ids = guildFilters;

    try {
      await queryClient.ensureQueryData({
        queryKey: ["documents", "global", guildFilters, "", 1, PAGE_SIZE, undefined, undefined],
        queryFn: () => apiClient.get("/documents/", { params }).then((r) => r.data),
        staleTime: 30_000,
      });
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/MyDocumentsPage").then((m) => ({ default: m.MyDocumentsPage }))
  ),
});
