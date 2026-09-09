import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import type { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { parseListingKind } from "@/lib/marketplace";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$guildId/marketplace_/$publicId"
)({
  // Carried so the back link can return to the shelf the listing was found on.
  validateSearch: (search: Record<string, unknown>): { kind?: ListingKind } => {
    const kind = parseListingKind(search.kind);
    return kind ? { kind } : {};
  },
  component: lazyRouteComponent(() =>
    import("@/pages/marketplace/MarketplaceListingPage").then((m) => ({
      default: m.MarketplaceListingPage,
    }))
  ),
});
