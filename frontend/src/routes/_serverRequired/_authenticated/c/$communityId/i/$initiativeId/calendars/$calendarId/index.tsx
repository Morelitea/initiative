import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/$calendarId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarsPage").then((m) => ({
      default: m.CalendarFocusPage,
    }))
  ),
});
