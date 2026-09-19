import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/integrations"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPlatformIntegrationsPage").then((m) => ({
      default: m.SettingsPlatformIntegrationsPage,
    }))
  ),
});
