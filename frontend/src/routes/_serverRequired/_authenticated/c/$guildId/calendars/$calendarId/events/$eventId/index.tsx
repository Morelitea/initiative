import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/calendars/$calendarId/events/$eventId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventDetailPage").then((m) => ({
      default: m.EventDetailPage,
    }))
  ),
});
