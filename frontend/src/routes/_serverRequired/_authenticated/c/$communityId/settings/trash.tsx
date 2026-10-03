import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/trash"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityTrashPage").then((m) => ({
      default: m.SettingsCommunityTrashPage,
    }))
  ),
});
