import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin")({
  component: lazyRouteComponent(() =>
    import("@/pages/AdminSettingsLayout").then((m) => ({ default: m.AdminSettingsLayout }))
  ),
});
