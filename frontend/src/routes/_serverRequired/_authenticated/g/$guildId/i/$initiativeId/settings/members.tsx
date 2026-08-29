import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/i/$initiativeId/settings/members"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsMembersPage").then((m) => ({
      default: m.InitiativeSettingsMembersPage,
    }))
  ),
});
