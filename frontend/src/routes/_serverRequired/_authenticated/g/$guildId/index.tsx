import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/")({
  component: lazyRouteComponent(() =>
    import("@/pages/GuildDashboardPage").then((m) => ({ default: m.GuildDashboardPage }))
  ),
});
