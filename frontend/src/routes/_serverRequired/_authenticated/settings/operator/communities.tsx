import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/operator/communities"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/OperatorDashboardCommunitiesPage").then((m) => ({
      default: m.OperatorDashboardCommunitiesPage,
    }))
  ),
});
