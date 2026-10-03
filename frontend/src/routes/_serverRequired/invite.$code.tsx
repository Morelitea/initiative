import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/invite/$code")({
  component: lazyRouteComponent(() =>
    import("@/pages/CommunityInvitePage").then((m) => ({ default: m.CommunityInvitePage }))
  ),
});
