import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/push")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPushPage").then((m) => ({ default: m.SettingsPushPage }))
  ),
});
