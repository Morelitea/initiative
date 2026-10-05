import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/account/not-me")({
  component: lazyRouteComponent(() =>
    import("@/pages/AccountNotMePage").then((m) => ({ default: m.AccountNotMePage }))
  ),
});
