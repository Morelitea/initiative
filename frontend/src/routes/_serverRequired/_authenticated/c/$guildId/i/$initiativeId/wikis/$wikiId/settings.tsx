import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/wikis/WikiSettingsPage").then((m) => ({
      default: m.WikiSettingsPage,
    }))
  ),
});
