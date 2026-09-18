import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/access")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsAccessGrantsPage").then((m) => ({
      default: m.SettingsAccessGrantsPage,
    }))
  ),
});
