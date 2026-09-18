import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPlatformUsersPage").then((m) => ({
      default: m.SettingsPlatformUsersPage,
    }))
  ),
});
