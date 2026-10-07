import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/task-statuses"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectSettingsTaskStatusesPage").then((m) => ({
      default: m.ProjectSettingsTaskStatusesPage,
    }))
  ),
});
