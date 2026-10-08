import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { getReadFileQueryKey, readFile } from "@/api/generated/files/files";
import { commentThreadQueryOptions } from "@/hooks/useComments";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/$fileId/"
)({
  loader: ({ context, params }) => {
    const fileId = Number(params.fileId);
    const communityId = Number(params.communityId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void Promise.all([
      queryClient.ensureQueryData({
        queryKey: getReadFileQueryKey(communityId, fileId),
        queryFn: () => readFile(communityId, fileId),
        staleTime: 30_000,
      }),
      queryClient.ensureInfiniteQueryData({
        ...commentThreadQueryOptions(communityId, { file_id: fileId }),
        staleTime: 30_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/files/FileDetailPage").then((m) => ({
      default: m.FileDetailPage,
    }))
  ),
});
