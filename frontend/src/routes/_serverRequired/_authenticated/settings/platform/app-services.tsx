import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/app-services"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsAppServicesPage").then((m) => ({
      default: m.SettingsAppServicesPage,
    }))
  ),
});
