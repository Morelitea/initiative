import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/counter-groups/$counterGroupId/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/counters/CounterGroupDetailPage").then((m) => ({
      default: m.CounterGroupDetailPage,
    }))
  ),
});
