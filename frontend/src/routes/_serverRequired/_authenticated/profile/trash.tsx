import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/trash")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserTrashPage").then((m) => ({
      default: m.UserTrashPage,
    }))
  ),
});
