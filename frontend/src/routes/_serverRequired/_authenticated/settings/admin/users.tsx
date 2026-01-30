import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin/users")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPlatformUsersPage").then((m) => ({
      default: m.SettingsPlatformUsersPage,
    }))
  ),
});
