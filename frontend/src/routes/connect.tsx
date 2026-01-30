import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/connect")({
  component: lazyRouteComponent(() =>
    import("@/pages/ConnectServerPage").then((m) => ({ default: m.ConnectServerPage }))
  ),
});
