import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/storage")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsStoragePage").then((m) => ({ default: m.SettingsStoragePage }))
  ),
});
