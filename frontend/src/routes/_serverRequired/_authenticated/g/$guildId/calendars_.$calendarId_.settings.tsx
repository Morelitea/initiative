import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/calendars_/$calendarId_/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarSettingsPage").then((m) => ({
      default: m.CalendarSettingsPage,
    }))
  ),
});
