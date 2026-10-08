import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/integrations"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityIntegrationsPage").then((m) => ({
      default: m.SettingsCommunityIntegrationsPage,
    }))
  ),
});
