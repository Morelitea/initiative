import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/documents_/$documentId_/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/DocumentSettingsPage").then((m) => ({ default: m.DocumentSettingsPage }))
  ),
});
