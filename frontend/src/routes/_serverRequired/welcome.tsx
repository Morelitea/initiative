import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/welcome")({
  component: lazyRouteComponent(() =>
    import("@/pages/landing/LandingCinematic").then((m) => ({ default: m.LandingCinematic }))
  ),
});
