import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  getListCommentsApiV1GGuildIdCommentsGetQueryKey,
  listCommentsApiV1GGuildIdCommentsGet,
} from "@/api/generated/comments/comments";
import {
  getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey,
  readDocumentApiV1GGuildIdDocumentsDocumentIdGet,
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
        queryKey: getReadDocumentApiV1GGuildIdDocumentsDocumentIdGetQueryKey(guildId, documentId),
        queryFn: () => readDocumentApiV1GGuildIdDocumentsDocumentIdGet(guildId, documentId),
        staleTime: 30_000,
      }),
      queryClient.ensureQueryData({
        queryKey: getListCommentsApiV1GGuildIdCommentsGetQueryKey(guildId, {
          document_id: documentId,
        }),
        queryFn: () => listCommentsApiV1GGuildIdCommentsGet(guildId, { document_id: documentId }),
        staleTime: 30_000,
      }),
    ]).catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage }))
  ),
});
