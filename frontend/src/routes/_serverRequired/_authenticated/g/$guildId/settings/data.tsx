import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/data")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildDataPage").then((m) => ({
      default: m.SettingsGuildDataPage,
    }))
  ),
});
