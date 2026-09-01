import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/projects/$projectId/settings"
)({
  // A link may point at one tab — "Manage presets" from the task list does.
  validateSearch: (search: Record<string, unknown>) => ({
    tab: typeof search.tab === "string" ? search.tab : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectSettingsPage").then((m) => ({ default: m.ProjectSettingsPage }))
  ),
});
