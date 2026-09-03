import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/projects/$projectId/settings/task-statuses"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/projectSettings/ProjectSettingsTaskStatusesPage").then((m) => ({
      default: m.ProjectSettingsTaskStatusesPage,
    }))
  ),
});
