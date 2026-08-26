import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/apps/connected")({
  component: lazyRouteComponent(() =>
    import("@/pages/apps/AppConnectedPage").then((m) => ({ default: m.AppConnectedPage }))
  ),
});
