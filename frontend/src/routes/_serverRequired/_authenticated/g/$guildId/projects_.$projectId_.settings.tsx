import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/projects_/$projectId_/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectSettingsPage").then((m) => ({ default: m.ProjectSettingsPage }))
  ),
});
