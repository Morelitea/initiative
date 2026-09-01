import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/calendars/$calendarId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarsPage").then((m) => ({
      default: m.CalendarFocusPage,
    }))
  ),
});
