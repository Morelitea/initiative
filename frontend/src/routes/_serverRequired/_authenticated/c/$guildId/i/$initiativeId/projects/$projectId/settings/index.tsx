import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// Details is what a project's settings open on, so it is served at `/settings`
// itself rather than redirecting to a `/settings/details` alias.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/projects/$projectId/settings/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/toolSettings/ToolSettingsDetailsPage").then((m) => ({
      default: m.ToolSettingsDetailsPage,
    }))
  ),
});
