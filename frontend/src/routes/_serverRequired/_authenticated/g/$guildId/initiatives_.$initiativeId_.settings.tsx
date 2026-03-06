import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

type InitiativeSettingsSearch = {
  tab?: string;
};

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/initiatives_/$initiativeId_/settings"
)({
  validateSearch: (search: Record<string, unknown>): InitiativeSettingsSearch => ({
    tab: typeof search.tab === "string" ? search.tab : undefined,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/InitiativeSettingsPage").then((m) => ({ default: m.InitiativeSettingsPage }))
  ),
});
