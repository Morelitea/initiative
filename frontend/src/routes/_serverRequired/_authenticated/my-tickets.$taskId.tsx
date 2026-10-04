import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// Not under `/c/$communityId`: a ticket is the filer's own, followed from outside
// the community that works it — they are not a member there.
export const Route = createFileRoute("/_serverRequired/_authenticated/my-tickets/$taskId")({
  component: lazyRouteComponent(() =>
    import("@/pages/user/TicketPage").then((m) => ({ default: m.TicketPage }))
  ),
});
