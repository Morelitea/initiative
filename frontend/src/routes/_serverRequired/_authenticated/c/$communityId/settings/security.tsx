import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/security"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunitySecurityPage").then((m) => ({
      default: m.SettingsCommunitySecurityPage,
    }))
  ),
});
