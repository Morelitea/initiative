import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { validateAccessGrantsSearch } from "@/lib/accessGrantsSearch";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/access")({
  validateSearch: validateAccessGrantsSearch,
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsAccessGrantsPage").then((m) => ({
      default: m.SettingsAccessGrantsPage,
    }))
  ),
});
