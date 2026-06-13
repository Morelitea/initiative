import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/import")({
  component: lazyRouteComponent(() =>
    import("@/pages/user/settings/UserSettingsImportPage").then((m) => ({
      default: m.UserSettingsImportPage,
    }))
  ),
});
