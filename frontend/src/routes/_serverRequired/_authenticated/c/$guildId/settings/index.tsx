import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// No page of its own: `/settings` sends each person to the first tab they may
// open — see SettingsGuildIndexPage.
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/settings/")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildIndexPage").then((m) => ({ default: m.SettingsGuildIndexPage }))
  ),
});
