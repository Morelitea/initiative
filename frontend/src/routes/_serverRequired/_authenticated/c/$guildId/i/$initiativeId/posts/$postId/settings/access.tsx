import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/posts/$postId/settings/access"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/toolSettings/ToolSettingsAccessPage").then((m) => ({
      default: m.ToolSettingsAccessPage,
    }))
  ),
});
