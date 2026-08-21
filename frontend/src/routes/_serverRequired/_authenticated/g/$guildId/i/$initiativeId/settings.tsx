import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/InitiativeSettingsPage").then((m) => ({ default: m.InitiativeSettingsPage }))
  ),
});
