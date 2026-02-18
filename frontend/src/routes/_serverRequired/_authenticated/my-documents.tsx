import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";
import { getItem } from "@/lib/storage";

type MyDocumentsSearchParams = {
  page?: number;
};

const STORAGE_KEY = "initiative-my-documents-filters";
const PAGE_SIZE = 20;

function readStoredFilters() {
  try {
    const raw = getItem(STORAGE_KEY);
    if (!raw) return { guildFilters: [] as number[] };
    const parsed = JSON.parse(raw);
    return {
      guildFilters: Array.isArray(parsed?.guildFilters) ? parsed.guildFilters : [],
    };
  } catch {
    return { guildFilters: [] as number[] };
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
    const { guildFilters } = readStoredFilters();

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
