import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/g/$guildId/marketplace_/$publicId"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/marketplace/MarketplaceListingPage").then((m) => ({
      default: m.MarketplaceListingPage,
    }))
  ),
});
