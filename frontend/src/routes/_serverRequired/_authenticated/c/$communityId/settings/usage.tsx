import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/usage"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityUsagePage").then((m) => ({
      default: m.SettingsCommunityUsagePage,
    }))
  ),
});
