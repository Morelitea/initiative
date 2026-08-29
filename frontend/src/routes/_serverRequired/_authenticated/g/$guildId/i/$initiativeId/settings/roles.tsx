import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/settings/roles"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsRolesPage").then((m) => ({
      default: m.InitiativeSettingsRolesPage,
    }))
  ),
});
