import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/$fileId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/files/FileSettingsPage").then((m) => ({
      default: m.FileSettingsPage,
    }))
  ),
});
