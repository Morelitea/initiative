import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/**
 * A document somebody put in this wiki, read as one of its pages.
 *
 * A sibling of the wiki's own pages rather than a redirect to the document,
 * because the point of putting a document in a wiki is that it is read with
 * the wiki's navigation beside it. Editing it goes to the document's own
 * address, where it is edited like any other document.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/documents/$documentId"
)({
  staticData: { fullBleed: true },
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/wikis/WikiDocumentView").then((m) => ({
      default: m.WikiDocumentView,
    }))
  ),
});
