import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/events_/$eventId")(
  {
    component: lazyRouteComponent(() =>
      import("@/pages/initiativeTools/events/EventDetailPage").then((m) => ({
        default: m.EventDetailPage,
      }))
    ),
  }
);
