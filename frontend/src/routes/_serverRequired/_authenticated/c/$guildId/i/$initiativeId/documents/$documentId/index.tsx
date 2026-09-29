import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getListCommentsApiV1CGuildIdCommentsGetQueryKey,
  listCommentsApiV1CGuildIdCommentsGet,
} from "@/api/generated/comments/comments";
import {
  getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey,
  readDocumentApiV1CGuildIdDocumentsDocumentIdGet,
} from "@/api/generated/documents/documents";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/documents/$documentId/"
)({
  loader: ({ context, params }) => {
    const documentId = Number(params.documentId);
    const guildId = Number(params.guildId);
    const { queryClient } = context;

    // Warm the cache without holding the navigation on it: the page draws
    // its placeholder at once and the reads land into it. A failed prefetch
    // is swallowed here; the page fetches for itself and reports the error.
    void Promise.all([
      queryClient.ensureQueryData({
        queryKey: getReadDocumentApiV1CGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId),
        queryFn: () => readDocumentApiV1CGuildIdDocumentsDocumentIdGet(guildId, documentId),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getListCommentsApiV1CGuildIdCommentsGetQueryKey(guildId, {
          document_id: documentId,
        }),
        queryFn: () => listCommentsApiV1CGuildIdCommentsGet(guildId, { document_id: documentId }),
        staleTime: 30_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage }))
  ),
});
