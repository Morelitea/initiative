import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/calendars/$calendarId/events/$eventId/"
)({
  validateSearch: (search: Record<string, unknown>): { occurrence?: string } => ({
    occurrence: typeof search.occurrence === "string" ? search.occurrence : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventDetailPage").then((m) => ({
      default: m.EventDetailPage,
    }))
  ),
});
