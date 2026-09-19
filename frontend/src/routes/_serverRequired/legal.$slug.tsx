import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/legal/$slug")({
  component: lazyRouteComponent(() =>
    import("@/pages/LegalDocumentPage").then((m) => ({ default: m.LegalDocumentPage }))
  ),
});
