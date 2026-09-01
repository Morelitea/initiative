import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/calendars/$calendarId/events/$eventId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventSettingsPage").then((m) => ({
      default: m.EventSettingsPage,
    }))
  ),
});
