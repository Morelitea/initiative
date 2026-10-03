import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/community/$communityId/login")({
  component: lazyRouteComponent(() =>
    import("@/pages/CommunityLoginPage").then((m) => ({ default: m.CommunityLoginPage }))
  ),
});
