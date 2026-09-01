import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/u/$userId")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserProfilePage").then((m) => ({ default: m.UserProfilePage }))
  ),
});
