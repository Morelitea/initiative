import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { parseViewSlug } from "@/lib/filters/viewSearch";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/views"
)({
  // What the editor opens on: a view, or the task page.
  validateSearch: (search: Record<string, unknown>) => ({
    view: parseViewSlug(search.view),
    page: search.page === "task" ? ("task" as const) : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectViewEditorPage").then((m) => ({
      default: m.ProjectViewEditorPage,
    }))
  ),
});
