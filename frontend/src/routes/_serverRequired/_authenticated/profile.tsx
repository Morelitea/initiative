import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile")({
  component: lazyRouteComponent(() =>
    import("@/pages/user/settings/UserSettingsLayout").then((m) => ({
      default: m.UserSettingsLayout,
    }))
  ),
});
