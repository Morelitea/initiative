import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/documents/$documentId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentSettingsPage").then((m) => ({ default: m.DocumentSettingsPage }))
  ),
});
