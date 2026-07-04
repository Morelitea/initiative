import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { toolListSearch } from "@/lib/tools/toolListSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/documents")({
  validateSearch: (search: Record<string, unknown>) => toolListSearch(search, { page: true }),
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage }))
  ),
});
