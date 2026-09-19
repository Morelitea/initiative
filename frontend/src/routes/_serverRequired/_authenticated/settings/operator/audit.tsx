import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/audit")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsPlatformAuditPage").then((m) => ({
      default: m.SettingsPlatformAuditPage,
    }))
  ),
});
