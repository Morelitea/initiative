import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { toolListSearch } from "@/lib/tools/toolListSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/counter-groups")({
  validateSearch: (search: Record<string, unknown>) => toolListSearch(search),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/counters/CounterGroupsPage").then((m) => ({
      default: m.CounterGroupsPage,
    }))
  ),
});
