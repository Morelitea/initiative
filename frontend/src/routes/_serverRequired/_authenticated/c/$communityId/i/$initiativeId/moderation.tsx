import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/moderation"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/ModerationPage").then((m) => ({ default: m.ModerationPage }))
  ),
});
