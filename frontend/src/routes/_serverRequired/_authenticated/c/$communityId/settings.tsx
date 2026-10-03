import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/settings")({
  component: lazyRouteComponent(() =>
    import("@/pages/CommunitySettingsLayout").then((m) => ({ default: m.CommunitySettingsLayout }))
  ),
});
