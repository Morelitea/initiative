import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

/** Which shelf of the marketplace to show. Read off the generated enum rather
 *  than restated here, so a kind added server-side is accepted without an edit.
 *  Anything unrecognized normalizes to dashboards. */
const KINDS = Object.values(ListingKind);

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/marketplace")({
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
