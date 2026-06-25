import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin/guilds")({
  component: lazyRouteComponent(() =>
    import("@/pages/AdminDashboardGuildsPage").then((m) => ({
      default: m.AdminDashboardGuildsPage,
    }))
  ),
});
