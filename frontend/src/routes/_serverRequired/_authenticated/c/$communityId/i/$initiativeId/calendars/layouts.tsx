import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/calendars/layouts"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarLayoutEditorPage").then((m) => ({
      default: m.CalendarLayoutEditorPage,
    }))
  ),
});
