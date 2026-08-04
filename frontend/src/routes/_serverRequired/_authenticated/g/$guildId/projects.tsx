import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearch } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/projects")({
  validateSearch: validateToolListSearch,
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage }))
  ),
});
