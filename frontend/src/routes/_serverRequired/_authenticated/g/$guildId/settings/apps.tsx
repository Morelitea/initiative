import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/apps")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildAppsPage").then((m) => ({
      default: m.SettingsGuildAppsPage,
    }))
  ),
});
