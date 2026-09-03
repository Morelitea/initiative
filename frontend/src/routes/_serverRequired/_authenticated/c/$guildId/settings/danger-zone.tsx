import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/settings/danger-zone"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildDangerZonePage").then((m) => ({
      default: m.SettingsGuildDangerZonePage,
    }))
  ),
});
