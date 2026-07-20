import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/guild/$guildId/login")({
  component: lazyRouteComponent(() =>
    import("@/pages/GuildLoginPage").then((m) => ({ default: m.GuildLoginPage }))
  ),
});
