import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateToolListSearchWithPage } from "@/lib/routeSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/dashboards")({
  validateSearch: validateToolListSearchWithPage,
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/dashboards/DashboardsPage").then((m) => ({
      default: m.DashboardsPage,
    }))
  ),
});
