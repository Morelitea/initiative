import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import {
  readDocumentApiV1DocumentsDocumentIdGet,
  getReadDocumentApiV1DocumentsDocumentIdGetQueryKey,
} from "@/api/generated/documents/documents";
import {
  listCommentsApiV1CommentsGet,
  getListCommentsApiV1CommentsGetQueryKey,
} from "@/api/generated/comments/comments";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/documents_/$documentId"
)({
  loader: async ({ context, params }) => {
    const documentId = Number(params.documentId);
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      await Promise.all([
        queryClient.ensureQueryData({
          queryKey: getReadDocumentApiV1DocumentsDocumentIdGetQueryKey(documentId),
          queryFn: () => readDocumentApiV1DocumentsDocumentIdGet(documentId),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData({
          queryKey: getListCommentsApiV1CommentsGetQueryKey({ document_id: documentId }),
          queryFn: () => listCommentsApiV1CommentsGet({ document_id: documentId }),
          staleTime: 30_000,
        }),
      ]);
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage }))
  ),
});
