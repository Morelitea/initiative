import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/queues_/$queueId")(
  {
    component: lazyRouteComponent(() =>
      import("@/pages/initiativeTools/queues/QueueDetailPage").then((m) => ({
        default: m.QueueDetailPage,
      }))
    ),
  }
);
