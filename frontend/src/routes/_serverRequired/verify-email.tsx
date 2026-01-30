import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/verify-email")({
  component: lazyRouteComponent(() =>
    import("@/pages/VerifyEmailPage").then((m) => ({ default: m.VerifyEmailPage }))
  ),
});
