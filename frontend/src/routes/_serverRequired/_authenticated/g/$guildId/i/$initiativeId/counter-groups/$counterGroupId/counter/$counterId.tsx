import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/counter-groups/$counterGroupId/counter/$counterId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/counters/CounterDetailPage").then((m) => ({
      default: m.CounterDetailPage,
    }))
  ),
});
