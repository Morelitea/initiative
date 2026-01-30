import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/admin/ai")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsAIPage").then((m) => ({ default: m.SettingsAIPage }))
  ),
});
