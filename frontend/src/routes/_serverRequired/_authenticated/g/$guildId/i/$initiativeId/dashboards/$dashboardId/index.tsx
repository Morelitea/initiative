import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/dashboards/$dashboardId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/DashboardDetailPage").then((m) => ({
      default: m.DashboardDetailPage,
    }))
  ),
});
