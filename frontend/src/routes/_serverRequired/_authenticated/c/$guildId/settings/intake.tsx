import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/settings/intake")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildIntakePage").then((m) => ({
      default: m.SettingsGuildIntakePage,
    }))
  ),
});
