import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/data"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityDataPage").then((m) => ({
      default: m.SettingsCommunityDataPage,
    }))
  ),
});
