import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/admin/announcements"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPlatformAnnouncementsPage").then((m) => ({
      default: m.SettingsPlatformAnnouncementsPage,
    }))
  ),
});
