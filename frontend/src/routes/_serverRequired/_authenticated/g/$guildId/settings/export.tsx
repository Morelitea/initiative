import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/export")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildExportPage").then((m) => ({
      default: m.SettingsGuildExportPage,
    }))
  ),
});
