import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/login")({
  component: lazyRouteComponent(() =>
    import("@/pages/LoginPage").then((m) => ({ default: m.LoginPage }))
  ),
});
