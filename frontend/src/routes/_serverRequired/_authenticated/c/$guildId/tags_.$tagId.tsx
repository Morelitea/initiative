import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getGetTagApiV1CGuildIdTagsTagIdGetQueryKey,
  getGetTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGetQueryKey,
  getTagApiV1CGuildIdTagsTagIdGet,
  getTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGet,
} from "@/api/generated/tags/tags";
import { type PageSearch, validatePage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/tags_/$tagId")({
  validateSearch: (search: Record<string, unknown>): PageSearch => ({
    page: validatePage(search.page),
  }),
  loader: ({ context, params }) => {
    const guildId = Number(params.guildId);
    const tagId = Number(params.tagId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void Promise.all([
      queryClient.ensureQueryData({
        queryKey: getGetTagApiV1CGuildIdTagsTagIdGetQueryKey(guildId, tagId),
        queryFn: () => getTagApiV1CGuildIdTagsTagIdGet(guildId, tagId),
        staleTime: 60_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getGetTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGetQueryKey(guildId, tagId),
        queryFn: () => getTagEntitiesApiV1CGuildIdTagsTagIdEntitiesGet(guildId, tagId),
        staleTime: 30_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/TagDetailPage").then((m) => ({ default: m.TagDetailPage }))
  ),
});
