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
  "/_serverRequired/_authenticated/g/$guildId/documents_/$documentId"
)({
  loader: async ({ context, params }) => {
    const documentId = Number(params.documentId);
    const guildId = Number(params.guildId);
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      await Promise.all([
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
      ]);
    } catch {
      // Silently fail - component will fetch its own data
    }
  },
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage }))
  ),
});
