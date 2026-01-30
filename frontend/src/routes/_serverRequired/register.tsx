import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/register")({
  component: lazyRouteComponent(() =>
    import("@/pages/RegisterPage").then((m) => ({ default: m.RegisterPage }))
  ),
});
