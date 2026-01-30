import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/guild/")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildPage").then((m) => ({ default: m.SettingsGuildPage }))
  ),
});
