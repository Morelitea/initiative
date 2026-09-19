import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/"
)({
  // A wiki is a surface, not a page in the reading column: it puts its
  // own header against the top and scrolls its own middle.
  staticData: { fullBleed: true },
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/wikis/WikiDetailPage").then((m) => ({
      default: m.WikiDetailPage,
    }))
  ),
});
