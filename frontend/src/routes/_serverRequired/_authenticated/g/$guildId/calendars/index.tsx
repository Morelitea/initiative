import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/calendars/")({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/events/CalendarsPage").then((m) => ({
      default: m.GuildCalendarsPage,
    }))
  ),
});
