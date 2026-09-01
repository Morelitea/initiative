import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/apps/$appId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/apps/GuildAppRoute").then((m) => ({ default: m.InitiativeAppRoute }))
  ),
});
