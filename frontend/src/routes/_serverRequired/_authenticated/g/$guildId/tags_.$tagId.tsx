import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getGetTagApiV1GGuildIdTagsTagIdGetQueryKey,
  getGetTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGetQueryKey,
  getTagApiV1GGuildIdTagsTagIdGet,
  getTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGet,
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
    const guildId = Number(params.guildId);
    const tagId = Number(params.tagId);
    const { queryClient } = context;

    // Prefetch tag and entities in parallel
    try {
      await Promise.all([
        queryClient.ensureQueryData({
          queryKey: getGetTagApiV1GGuildIdTagsTagIdGetQueryKey(guildId, tagId),
          queryFn: () => getTagApiV1GGuildIdTagsTagIdGet(guildId, tagId),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getGetTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGetQueryKey(guildId, tagId),
          queryFn: () => getTagEntitiesApiV1GGuildIdTagsTagIdEntitiesGet(guildId, tagId),
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
