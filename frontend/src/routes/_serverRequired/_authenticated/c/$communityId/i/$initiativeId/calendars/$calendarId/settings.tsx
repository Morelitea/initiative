import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/$calendarId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarSettingsPage").then((m) => ({
      default: m.CalendarSettingsPage,
    }))
  ),
});
