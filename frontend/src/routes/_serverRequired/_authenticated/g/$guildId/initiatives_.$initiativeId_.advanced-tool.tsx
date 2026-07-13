import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/initiatives_/$initiativeId_/advanced-tool"
)({
  validateSearch: (search: Record<string, unknown>): { create?: string } => ({
    create: typeof search.create === "string" ? search.create : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/AdvancedToolPage").then((m) => ({
      default: m.AdvancedToolPage,
    }))
  ),
});
