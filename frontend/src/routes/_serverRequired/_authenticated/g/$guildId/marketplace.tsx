import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute("/_serverRequired/_authenticated/g/$guildId/marketplace")({
  component: lazyRouteComponent(() =>
    import("@/pages/marketplace/MarketplaceBrowsePage").then((m) => ({
      default: m.MarketplaceBrowsePage,
    }))
  ),
});
