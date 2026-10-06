import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/**
 * Layout for one project's settings: the header, the tab bar, and whichever
 * section the address names. Each section is a route of its own beneath this
 * one, so `/settings/task-statuses` can be linked to and bookmarked.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectSettingsPage").then((m) => ({
      default: m.ProjectSettingsPage,
    }))
  ),
});
