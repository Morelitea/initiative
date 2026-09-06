import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/posts/$postId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/posts/PostDetailPage").then((m) => ({
      default: m.PostDetailPage,
    }))
  ),
});
