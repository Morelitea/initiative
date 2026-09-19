import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/settings/integrations"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildIntegrationsPage").then((m) => ({
      default: m.SettingsGuildIntegrationsPage,
    }))
  ),
});
