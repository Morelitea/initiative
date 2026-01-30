import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/initiatives_/$initiativeId")({
  component: lazyRouteComponent(() =>
    import("@/pages/InitiativeDetailPage").then((m) => ({ default: m.InitiativeDetailPage }))
  ),
});
