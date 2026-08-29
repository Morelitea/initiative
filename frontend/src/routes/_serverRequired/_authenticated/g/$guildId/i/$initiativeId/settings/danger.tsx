import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/settings/danger"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsDangerPage").then((m) => ({
      default: m.InitiativeSettingsDangerPage,
    }))
  ),
});
