import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

type DocumentsSearchParams = {
  create?: string;
  initiativeId?: string;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/documents")({
  validateSearch: (search: Record<string, unknown>): DocumentsSearchParams => ({
    create: typeof search.create === "string" ? search.create : undefined,
    initiativeId: typeof search.initiativeId === "string" ? search.initiativeId : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage }))
  ),
});
