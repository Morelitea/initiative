import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/queues/$queueId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/queues/QueueDetailPage").then((m) => ({
      default: m.QueueDetailPage,
    }))
  ),
});
