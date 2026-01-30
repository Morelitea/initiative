import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/guild/ai")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildAIPage").then((m) => ({ default: m.SettingsGuildAIPage }))
  ),
});
