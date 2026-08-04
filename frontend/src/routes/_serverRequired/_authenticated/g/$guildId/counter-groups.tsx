import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearch } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/counter-groups")({
  validateSearch: validateToolListSearch,
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/counters/CounterGroupsPage").then((m) => ({
      default: m.CounterGroupsPage,
    }))
  ),
});
