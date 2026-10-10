import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/views"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarViewEditorPage").then((m) => ({
      default: m.CalendarViewEditorPage,
    }))
  ),
});
