import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// No page of its own: `/settings` sends each person to the first tab they may
// open — see SettingsCommunityIndexPage.
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/settings/")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsCommunityIndexPage").then((m) => ({
      default: m.SettingsCommunityIndexPage,
    }))
  ),
});
