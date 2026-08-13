import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

const KINDS = Object.values(ListingKind);

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/marketplace_/$publicId"
)({
  // Carried so the back link can return to the shelf the listing was found on.
  validateSearch: (search: Record<string, unknown>): { kind?: ListingKind } =>
    KINDS.includes(search.kind as ListingKind) ? { kind: search.kind as ListingKind } : {},
  component: lazyRouteComponent(() =>
    import("@/pages/marketplace/MarketplaceListingPage").then((m) => ({
      default: m.MarketplaceListingPage,
    }))
  ),
});
