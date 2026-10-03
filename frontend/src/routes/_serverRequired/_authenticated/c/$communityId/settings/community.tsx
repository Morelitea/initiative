import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/community"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityPage").then((m) => ({ default: m.SettingsCommunityPage }))
  ),
});
