import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/invite/$code")({
  component: lazyRouteComponent(() =>
    import("@/pages/GuildInvitePage").then((m) => ({ default: m.GuildInvitePage }))
  ),
});
