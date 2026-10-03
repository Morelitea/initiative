import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/danger-zone"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityDangerZonePage").then((m) => ({
      default: m.SettingsCommunityDangerZonePage,
    }))
  ),
});
