import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/initiatives_/$initiativeId_/advanced-tool"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/AdvancedToolPage").then((m) => ({
      default: m.AdvancedToolPage,
    }))
  ),
});
