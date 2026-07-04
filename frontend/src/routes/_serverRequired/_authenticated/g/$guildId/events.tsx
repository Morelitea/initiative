import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { toolListSearch } from "@/lib/tools/toolListSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/events")({
  validateSearch: (search: Record<string, unknown>) => toolListSearch(search, { page: true }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventsPage").then((m) => ({ default: m.EventsPage }))
  ),
});
