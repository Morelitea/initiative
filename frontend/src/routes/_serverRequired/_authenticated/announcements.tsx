import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/announcements")({
  component: lazyRouteComponent(() =>
    import("@/pages/AnnouncementsArchivePage").then((m) => ({
      default: m.AnnouncementsArchivePage,
    }))
  ),
});
