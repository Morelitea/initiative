import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/licences")({
  component: lazyRouteComponent(() =>
    import("@/pages/LicencesPage").then((m) => ({ default: m.LicencesPage }))
  ),
});
