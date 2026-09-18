import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/**
 * One page of a wiki. A sibling route of the wiki's own index rather than a
 * search param, because a page is the thing people link to — a URL that names
 * it is the whole point of writing one.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/pages/$pageId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/wikis/WikiPageView").then((m) => ({
      default: m.WikiPageView,
    }))
  ),
});
