import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/settings/properties"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/PropertyDefinitionManagerPage").then((m) => ({
      default: m.PropertyDefinitionManagerPage,
    }))
  ),
});
