import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/settings/ai")({
  component: lazyRouteComponent(() =>
    import("@/pages/SettingsGuildAIPage").then((m) => ({ default: m.SettingsGuildAIPage }))
  ),
});
