import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/filter-presets"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/projectSettings/ProjectSettingsFilterPresetsPage").then((m) => ({
      default: m.ProjectSettingsFilterPresetsPage,
    }))
  ),
});
