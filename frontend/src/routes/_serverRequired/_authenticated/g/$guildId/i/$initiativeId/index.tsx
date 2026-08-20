import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateInitiativeToolSearch } from "@/lib/routeSearch";

const InitiativeDetailPage = lazyRouteComponent(() =>
  import("@/pages/InitiativeDetailPage").then((m) => ({ default: m.InitiativeDetailPage }))
);

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/")(
  {
    validateSearch: validateInitiativeToolSearch,
    // No tool in the path: the page shows the first tab this member can see.
    component: InitiativeDetailPage,
  }
);
