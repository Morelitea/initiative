import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";
import { apiClient } from "@/api/client";

export const Route = createFileRoute("/_serverRequired/_authenticated/documents_/$documentId")({
  loader: async ({ context, params }) => {
    const documentId = Number(params.documentId);
    const { queryClient } = context;

    // Prefetch in background - don't block navigation on failure
    try {
      await Promise.all([
        queryClient.ensureQueryData({
          queryKey: ["documents", documentId],
          queryFn: () => apiClient.get(`/documents/${documentId}`).then((r) => r.data),
          staleTime: 30_000,
        }),
        queryClient.ensureQueryData({
          queryKey: ["comments", "document", documentId],
          queryFn: () =>
            apiClient
              .get("/comments/", { params: { document_id: documentId } })
              .then((r) => r.data),
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
