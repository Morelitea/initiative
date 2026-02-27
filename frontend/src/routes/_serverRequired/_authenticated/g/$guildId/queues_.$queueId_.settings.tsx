import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/queues_/$queueId_/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/queues/QueueSettingsPage").then((m) => ({
      default: m.QueueSettingsPage,
    }))
  ),
});
