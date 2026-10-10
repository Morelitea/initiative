import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/views"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectSettingsViewsPage").then((m) => ({
      default: m.ProjectSettingsViewsPage,
    }))
  ),
});
