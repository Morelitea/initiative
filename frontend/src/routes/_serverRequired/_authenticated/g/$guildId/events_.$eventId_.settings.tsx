import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/events_/$eventId_/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/EventSettingsPage").then((m) => ({
      default: m.EventSettingsPage,
    }))
  ),
});
