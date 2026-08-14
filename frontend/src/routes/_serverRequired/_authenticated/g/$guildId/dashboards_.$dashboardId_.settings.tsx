import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/dashboards_/$dashboardId_/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/DashboardSettingsPage").then((m) => ({
      default: m.DashboardSettingsPage,
    }))
  ),
});
