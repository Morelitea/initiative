import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/calendars/$calendarId/events/$eventId/settings"
)({
  validateSearch: (search: Record<string, unknown>): { occurrence?: string } => ({
    occurrence: typeof search.occurrence === "string" ? search.occurrence : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventSettingsPage").then((m) => ({
      default: m.EventSettingsPage,
    }))
  ),
});
