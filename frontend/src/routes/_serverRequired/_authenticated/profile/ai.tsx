import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/profile/ai")({
  component: lazyRouteComponent(() =>
    import("@/pages/UserSettingsAIPage").then((m) => ({ default: m.UserSettingsAIPage }))
  ),
});
