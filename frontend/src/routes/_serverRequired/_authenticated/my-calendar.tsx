import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/my-calendar")({
  component: lazyRouteComponent(() =>
    import("@/pages/MyCalendarPage").then((m) => ({ default: m.MyCalendarPage }))
  ),
});
