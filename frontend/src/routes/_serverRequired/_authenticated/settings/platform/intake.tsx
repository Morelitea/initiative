import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/intake")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsIntakePage").then((m) => ({ default: m.SettingsIntakePage }))
  ),
});
