import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/settings/security"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildSecurityPage").then((m) => ({
      default: m.SettingsGuildSecurityPage,
    }))
  ),
});
