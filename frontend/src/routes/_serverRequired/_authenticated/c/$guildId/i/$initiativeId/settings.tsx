import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/**
 * Layout for one initiative's settings: the header, the tab bar, and whichever
 * section the address names. Each section is a route of its own beneath this
 * one, so `/settings/members` can be linked to and bookmarked.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/i/$initiativeId/settings"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/InitiativeSettingsLayout").then((m) => ({
      default: m.InitiativeSettingsLayout,
    }))
  ),
});
