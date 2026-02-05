import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings")({
  component: lazyRouteComponent(() =>
    import("@/pages/GuildSettingsLayout").then((m) => ({ default: m.GuildSettingsLayout }))
  ),
});
