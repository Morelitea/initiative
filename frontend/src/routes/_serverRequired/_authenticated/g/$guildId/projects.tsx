import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

type ProjectsSearchParams = {
  create?: string;
  initiativeId?: string;
};

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/projects")({
  validateSearch: (search: Record<string, unknown>): ProjectsSearchParams => ({
    create: typeof search.create === "string" ? search.create : undefined,
    initiativeId: typeof search.initiativeId === "string" ? search.initiativeId : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage }))
  ),
});
