import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/settings/advanced-tool"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildAdvancedToolPage").then((m) => ({
      default: m.SettingsGuildAdvancedToolPage,
    }))
  ),
});
