import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/trash")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildTrashPage").then((m) => ({ default: m.SettingsGuildTrashPage }))
  ),
});
