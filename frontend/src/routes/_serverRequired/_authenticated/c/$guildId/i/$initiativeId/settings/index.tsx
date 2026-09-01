import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

// Details is what an initiative's settings open on, so it is served at
// `/settings` itself rather than redirecting to a `/settings/details` alias.
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/settings/"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeSettings/InitiativeSettingsDetailsPage").then((m) => ({
      default: m.InitiativeSettingsDetailsPage,
    }))
  ),
});
