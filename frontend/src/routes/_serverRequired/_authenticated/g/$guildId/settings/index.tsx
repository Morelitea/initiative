import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildPage").then((m) => ({ default: m.SettingsGuildPage }))
  ),
});
