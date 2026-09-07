import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/posts/$postId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/posts/PostSettingsPage").then((m) => ({
      default: m.PostSettingsPage,
    }))
  ),
});
