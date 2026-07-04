import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { toolListSearch } from "@/lib/tools/toolListSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/projects")({
  validateSearch: (search: Record<string, unknown>) => toolListSearch(search),
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage }))
  ),
});
