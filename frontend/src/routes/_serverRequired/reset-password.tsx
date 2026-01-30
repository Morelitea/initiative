import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/reset-password")({
  component: lazyRouteComponent(() =>
    import("@/pages/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage }))
  ),
});
