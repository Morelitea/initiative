import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/plugins/connected")({
  component: lazyRouteComponent(() =>
    import("@/pages/plugins/PluginConnectedPage").then((m) => ({ default: m.PluginConnectedPage }))
  ),
});
