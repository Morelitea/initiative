import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/settings/community"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildPage").then((m) => ({ default: m.SettingsGuildPage }))
  ),
});
