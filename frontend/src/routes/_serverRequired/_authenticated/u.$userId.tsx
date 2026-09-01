import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// Not under `/c/$guildId` — a profile is public and the same page whoever
// opens it, so no part of it is a community's to scope.
export const Route = createFileRoute("/_serverRequired/_authenticated/u/$userId")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserProfilePage").then((m) => ({ default: m.UserProfilePage }))
  ),
});
