import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/dashboards/$dashboardId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/DashboardSettingsPage").then((m) => ({
      default: m.DashboardSettingsPage,
    }))
  ),
});
