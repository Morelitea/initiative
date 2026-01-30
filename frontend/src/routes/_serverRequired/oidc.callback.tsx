import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/oidc/callback")({
  component: lazyRouteComponent(() =>
    import("@/pages/OidcCallbackPage").then((m) => ({ default: m.OidcCallbackPage }))
  ),
});
