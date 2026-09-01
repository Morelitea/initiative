import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/dashboards/$dashboardId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/DashboardDetailPage").then((m) => ({
      default: m.DashboardDetailPage,
    }))
  ),
});
