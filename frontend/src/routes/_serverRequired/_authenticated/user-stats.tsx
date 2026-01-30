import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/user-stats")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserStatsPage").then((m) => ({ default: m.UserStatsPage }))
  ),
});
