import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/projects")({
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage }))
  ),
});
