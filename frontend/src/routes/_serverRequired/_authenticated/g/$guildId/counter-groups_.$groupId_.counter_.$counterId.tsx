import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/counter-groups_/$groupId_/counter_/$counterId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/counters/CounterDetailPage").then((m) => ({
      default: m.CounterDetailPage,
    }))
  ),
});
