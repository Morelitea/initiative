import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/dashboards_/$dashboardId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/DashboardDetailPage").then((m) => ({
      default: m.DashboardDetailPage,
    }))
  ),
});
