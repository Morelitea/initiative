import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/whats-new/")({
  component: lazyRouteComponent(() =>
    import("@/pages/landing/WhatsNewPage").then((m) => ({ default: m.WhatsNewPage }))
  ),
});
