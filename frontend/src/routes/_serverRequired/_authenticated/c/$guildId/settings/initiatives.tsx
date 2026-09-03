import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/settings/initiatives"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsInitiativesPage").then((m) => ({
      default: m.SettingsInitiativesPage,
    }))
  ),
});
