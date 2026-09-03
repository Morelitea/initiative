import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/settings/data")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildDataPage").then((m) => ({
      default: m.SettingsGuildDataPage,
    }))
  ),
});
