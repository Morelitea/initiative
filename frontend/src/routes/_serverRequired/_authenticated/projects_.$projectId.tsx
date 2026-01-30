import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/projects_/$projectId")({
  component: lazyRouteComponent(() =>
    import("@/pages/ProjectDetailPage").then((m) => ({ default: m.ProjectDetailPage }))
  ),
});
