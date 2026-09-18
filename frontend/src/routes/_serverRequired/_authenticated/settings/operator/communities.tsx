import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/operator/communities"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/OperatorDashboardGuildsPage").then((m) => ({
      default: m.OperatorDashboardGuildsPage,
    }))
  ),
});
