import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/plugins/$pluginId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/plugins/CommunityPluginRoute").then((m) => ({
      default: m.InitiativePluginRoute,
    }))
  ),
});
