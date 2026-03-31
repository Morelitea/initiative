import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/automations_/$automationId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/automations/AutomationEditorPage").then((m) => ({
      default: m.AutomationEditorPage,
    }))
  ),
});
