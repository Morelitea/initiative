import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/my-calendar-events")({
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyCalendarPage").then((m) => ({ default: m.MyCalendarPage }))
  ),
});
