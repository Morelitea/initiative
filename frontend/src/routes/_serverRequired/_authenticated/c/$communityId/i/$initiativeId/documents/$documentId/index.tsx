import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { getReadDocumentQueryKey, readDocument } from "@/api/generated/documents/documents";
import { commentThreadQueryOptions } from "@/hooks/useComments";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/documents/$documentId/"
)({
  loader: ({ context, params }) => {
    const documentId = Number(params.documentId);
    const communityId = Number(params.communityId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void Promise.all([
      queryClient.ensureQueryData({
        queryKey: getReadDocumentQueryKey(communityId, documentId),
        queryFn: () => readDocument(communityId, documentId),
        staleTime: 30_000,
      }),
      queryClient.ensureInfiniteQueryData({
        ...commentThreadQueryOptions(communityId, { document_id: documentId }),
        staleTime: 30_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage }))
  ),
});
