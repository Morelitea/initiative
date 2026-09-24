import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/placement")(
  {
    component: lazyRouteComponent(() =>
      import("@/pages/OperatorDashboardPlacementPage").then((m) => ({
        default: m.OperatorDashboardPlacementPage,
      }))
    ),
  }
);
