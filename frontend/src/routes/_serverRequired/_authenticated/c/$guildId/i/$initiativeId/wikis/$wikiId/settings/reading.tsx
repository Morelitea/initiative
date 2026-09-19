import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// How the wiki reads: the order its pages sit in, how wide they run, what sits
// beside them, and the colour it is recognised by. Too many to sit as a card on
// Details, so they take a section of their own.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/settings/reading"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/wikiSettings/WikiReadingSettingsPage").then((m) => ({
      default: m.WikiReadingSettingsPage,
    }))
  ),
});
