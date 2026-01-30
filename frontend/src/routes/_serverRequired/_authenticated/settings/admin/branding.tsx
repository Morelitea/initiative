import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin/branding")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsBrandingPage").then((m) => ({ default: m.SettingsBrandingPage }))
  ),
});
