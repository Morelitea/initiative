import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/billing")({
  component: lazyRouteComponent(() =>
    import("@/pages/OperatorDashboardBillingPage").then((m) => ({
      default: m.OperatorDashboardBillingPage,
    }))
  ),
});
