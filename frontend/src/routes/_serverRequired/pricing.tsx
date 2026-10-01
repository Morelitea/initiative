import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/pricing")({
  component: lazyRouteComponent(() =>
    import("@/pages/landing/PricingPage").then((m) => ({ default: m.PricingPage }))
  ),
});
