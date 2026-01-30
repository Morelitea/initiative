import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/forgot-password")({
  component: lazyRouteComponent(() =>
    import("@/pages/ForgotPasswordPage").then((m) => ({ default: m.ForgotPasswordPage }))
  ),
});
