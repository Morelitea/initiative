import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/initiatives")({
  component: lazyRouteComponent(() =>
    import("@/pages/InitiativesPage").then((m) => ({ default: m.InitiativesPage }))
  ),
});
