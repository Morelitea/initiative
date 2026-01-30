import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/")({
  component: lazyRouteComponent(() =>
    import("@/pages/MyTasksPage").then((m) => ({ default: m.MyTasksPage }))
  ),
});
