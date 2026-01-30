import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/documents")({
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage }))
  ),
});
