import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/auth")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildAuthPage").then((m) => ({ default: m.SettingsGuildAuthPage }))
  ),
});
