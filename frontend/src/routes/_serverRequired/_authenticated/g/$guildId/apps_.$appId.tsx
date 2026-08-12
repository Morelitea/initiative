import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/apps_/$appId")({
  component: lazyRouteComponent(() =>
    import("@/pages/GuildAppPage").then((m) => ({ default: m.GuildAppPage }))
  ),
});
