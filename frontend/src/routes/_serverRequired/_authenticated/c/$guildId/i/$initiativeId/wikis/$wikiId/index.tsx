import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/wikis/$wikiId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/wikis/WikiDetailPage").then((m) => ({
      default: m.WikiDetailPage,
    }))
  ),
});
