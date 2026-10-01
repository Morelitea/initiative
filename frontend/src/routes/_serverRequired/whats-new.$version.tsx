import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/whats-new/$version")({
  component: lazyRouteComponent(() =>
    import("@/pages/landing/WhatsNewPage").then((m) => ({ default: m.WhatsNewPostPage }))
  ),
});
