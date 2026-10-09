import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/** Which of the plug-in's pages to open, by id: what a task's block links to. */
interface PluginPageSearch {
  page?: string;
}

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/plugins/$pluginId"
)({
  validateSearch: (search: Record<string, unknown>): PluginPageSearch =>
    typeof search.page === "string" && search.page ? { page: search.page } : {},
  component: lazyRouteComponent(() =>
    import("@/pages/plugins/CommunityPluginRoute").then((m) => ({
      default: m.InitiativePluginRoute,
    }))
  ),
});
