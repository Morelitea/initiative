import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/settings/users")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsUsersPage").then((m) => ({ default: m.SettingsUsersPage }))
  ),
});
