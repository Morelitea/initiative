import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/my-tickets/")({
  component: lazyRouteComponent(() =>
    import("@/pages/user/MyTicketsPage").then((m) => ({ default: m.MyTicketsPage }))
  ),
});
