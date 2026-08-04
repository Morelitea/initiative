import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearchWithPage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/documents")({
  validateSearch: validateToolListSearchWithPage,
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage }))
  ),
});
