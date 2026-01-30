import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin/auth")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsAuthPage").then((m) => ({ default: m.SettingsAuthPage }))
  ),
});
