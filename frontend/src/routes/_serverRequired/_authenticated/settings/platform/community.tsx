import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/community")(
  {
    component: lazyRouteComponent(() =>
      import("@/pages/SettingsPlatformCommunityPage").then((m) => ({
        default: m.SettingsPlatformCommunityPage,
      }))
    ),
  }
);
