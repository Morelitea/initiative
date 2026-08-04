import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearchWithPage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/queues")({
  validateSearch: validateToolListSearchWithPage,
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/queues/QueuesPage").then((m) => ({ default: m.QueuesPage }))
  ),
});
