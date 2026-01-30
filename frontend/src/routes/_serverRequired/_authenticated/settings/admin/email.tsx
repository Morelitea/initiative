import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin/email")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsEmailPage").then((m) => ({ default: m.SettingsEmailPage }))
  ),
});
