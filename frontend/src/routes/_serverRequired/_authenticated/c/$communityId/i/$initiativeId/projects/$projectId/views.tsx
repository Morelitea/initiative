import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { parseViewSlug } from "@/lib/filters/viewSearch";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/views"
)({
  // The view the editor opens on.
  validateSearch: (search: Record<string, unknown>) => ({ view: parseViewSlug(search.view) }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/projects/ProjectViewEditorPage").then((m) => ({
      default: m.ProjectViewEditorPage,
    }))
  ),
});
