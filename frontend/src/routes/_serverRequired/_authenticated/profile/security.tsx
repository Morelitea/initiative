import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/security")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserSettingsSecurityPage").then((m) => ({
      default: m.UserSettingsSecurityPage,
    }))
  ),
});
