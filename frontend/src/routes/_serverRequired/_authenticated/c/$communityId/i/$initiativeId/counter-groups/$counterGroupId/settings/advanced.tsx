import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings/advanced"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/toolSettings/ToolSettingsAdvancedPage").then((m) => ({
      default: m.ToolSettingsAdvancedPage,
    }))
  ),
});
