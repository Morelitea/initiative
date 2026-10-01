import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/settings/usage")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildUsagePage").then((m) => ({
      default: m.SettingsGuildUsagePage,
    }))
  ),
});
