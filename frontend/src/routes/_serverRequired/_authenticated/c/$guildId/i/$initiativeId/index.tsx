import { createFileRoute } from "@tanstack/react-router";

import { LazyInitiativeDetailPage } from "@/lib/initiativeDetailRoute";
import { validateInitiativeToolSearch } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/")(
  {
    validateSearch: validateInitiativeToolSearch,
    // No tool in the path: the page shows the first tab this member can see.
    component: LazyInitiativeDetailPage,
  }
);
