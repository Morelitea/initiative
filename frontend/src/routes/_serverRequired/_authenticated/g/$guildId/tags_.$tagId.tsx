import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getTagApiV1TagsTagIdGet,
  getGetTagApiV1TagsTagIdGetQueryKey,
  getTagEntitiesApiV1TagsTagIdEntitiesGet,
  getGetTagEntitiesApiV1TagsTagIdEntitiesGetQueryKey,
} from "@/api/generated/tags/tags";

type TagDetailSearchParams = {
  page?: number;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/tags_/$tagId")({
  validateSearch: (search: Record<string, unknown>): TagDetailSearchParams => ({
    page:
      typeof search.page === "number" && search.page >= 1
        ? search.page
        : typeof search.page === "string" && Number(search.page) >= 1
          ? Number(search.page)
          : undefined,
  }),
  loader: async ({ context, params }) => {
    const tagId = Number(params.tagId);
    const { queryClient } = context;

    // Prefetch tag and entities in parallel
    try {
      await Promise.all([
        queryClient.ensureQueryData({
          queryKey: getGetTagApiV1TagsTagIdGetQueryKey(tagId),
          queryFn: () => getTagApiV1TagsTagIdGet(tagId),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getGetTagEntitiesApiV1TagsTagIdEntitiesGetQueryKey(tagId),
          queryFn: () => getTagEntitiesApiV1TagsTagIdEntitiesGet(tagId),
          staleTime: 30_000,
        }),
      ]);
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/TagDetailPage").then((m) => ({ default: m.TagDetailPage }))
  ),
});
