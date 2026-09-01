import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/settings/properties"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsPropertiesPage").then((m) => ({
      default: m.InitiativeSettingsPropertiesPage,
    }))
  ),
});
