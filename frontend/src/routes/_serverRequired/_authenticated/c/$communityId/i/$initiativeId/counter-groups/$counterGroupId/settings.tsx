import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/counters/CounterGroupSettingsPage").then((m) => ({
      default: m.CounterGroupSettingsPage,
    }))
  ),
});
