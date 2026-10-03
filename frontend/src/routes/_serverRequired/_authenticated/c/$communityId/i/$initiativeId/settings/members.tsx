import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/members"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsMembersPage").then((m) => ({
      default: m.InitiativeSettingsMembersPage,
    }))
  ),
});
