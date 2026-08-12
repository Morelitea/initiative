import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

/** Which shelf of the marketplace to show. Dashboards by default — apps are the
 *  smaller set, reached from the sidebar's add affordance. */
const KINDS = ["dashboard", "app"] as const;
type ListingKind = (typeof KINDS)[number];

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/marketplace")({
  validateSearch: (search: Record<string, unknown>): { kind: ListingKind } => ({
    kind: KINDS.includes(search.kind as ListingKind) ? (search.kind as ListingKind) : "dashboard",
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/marketplace/MarketplaceBrowsePage").then((m) => ({
      default: m.MarketplaceBrowsePage,
    }))
  ),
});
