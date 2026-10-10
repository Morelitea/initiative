import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/views"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsViewsPage").then((m) => ({
      default: m.InitiativeSettingsViewsPage,
    }))
  ),
});
