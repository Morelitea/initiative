import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearchWithPage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/calendar-events")({
  validateSearch: validateToolListSearchWithPage,
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventsPage").then((m) => ({ default: m.EventsPage }))
  ),
});
