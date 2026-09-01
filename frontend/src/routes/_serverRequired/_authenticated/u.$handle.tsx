import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// Addressed by handle — `/u/jordan1234` — not by id: the handle is what
// identifies someone in this product, and it is what a link is worth sharing.
// Not under `/c/$guildId`, because a profile is public and the same page
// whoever opens it, so no part of it is a community's to scope.
export const Route = createFileRoute("/_serverRequired/_authenticated/u/$handle")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserProfilePage").then((m) => ({ default: m.UserProfilePage }))
  ),
});
