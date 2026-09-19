import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/security")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPlatformSecurityPage").then((m) => ({
      default: m.SettingsPlatformSecurityPage,
    }))
  ),
});
