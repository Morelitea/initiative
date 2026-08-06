import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearchWithPage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/calendars")({
  validateSearch: validateToolListSearchWithPage,
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarsPage").then((m) => ({
      default: m.CalendarsPage,
    }))
  ),
});
