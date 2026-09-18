import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// The wiki's own settings — how it is ordered, read and coloured. Too many to
// sit as a card on Details, so they take a section of their own.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/settings/site"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/wikiSettings/WikiSiteSettingsPage").then((m) => ({
      default: m.WikiSiteSettingsPage,
    }))
  ),
});
