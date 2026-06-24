import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/platform/guilds")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildsPage").then((m) => ({ default: m.SettingsGuildsPage }))
  ),
});
