import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/welcome")({
  component: lazyRouteComponent(() =>
    import("@/pages/LandingPage").then((m) => ({ default: m.LandingPage }))
  ),
});
