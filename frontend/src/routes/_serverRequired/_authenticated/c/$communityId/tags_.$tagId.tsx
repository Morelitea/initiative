import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getGetTagEntitiesQueryKey,
  getGetTagQueryKey,
  getTag,
  getTagEntities,
} from "@/api/generated/tags/tags";
import { type PageSearch, validatePage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/tags_/$tagId")(
  {
    validateSearch: (search: Record<string, unknown>): PageSearch => ({
      page: validatePage(search.page),
    }),
    loader: ({ context, params }) => {
      const communityId = Number(params.communityId);
      const tagId = Number(params.tagId);
      const { queryClient } = context;

      // Warm the cache without holding the navigation on it: the page draws
      // its placeholder at once and the reads land into it. A failed prefetch
      // is swallowed here; the page fetches for itself and reports the error.
      void Promise.all([
        queryClient.ensureQueryData({
          queryKey: getGetTagQueryKey(communityId, tagId),
          queryFn: () => getTag(communityId, tagId),
          staleTime: 60_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getGetTagEntitiesQueryKey(communityId, tagId),
          queryFn: () => getTagEntities(communityId, tagId),
          staleTime: 30_000,
        }),
      ]).catch(() => {});
    },
    component: lazyRouteComponent(() =>
      import("@/pages/TagDetailPage").then((m) => ({ default: m.TagDetailPage }))
    ),
  }
);
