import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { COMMUNITY_SHELVES } from "@/lib/marketplace";

/** Which shelf of this community's marketplace to show. The shelves a person
 *  buys from — profile packs — have their own marketplace and are not here;
 *  see `@/lib/marketplace`. Anything unrecognized normalizes to dashboards. */
const KINDS = COMMUNITY_SHELVES;

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId/marketplace")({
  validateSearch: (search: Record<string, unknown>): { kind: ListingKind } => ({
    kind: KINDS.includes(search.kind as ListingKind)
      ? (search.kind as ListingKind)
      : ListingKind.dashboard,
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/marketplace/MarketplaceBrowsePage").then((m) => ({
      default: m.MarketplaceBrowsePage,
    }))
  ),
});
