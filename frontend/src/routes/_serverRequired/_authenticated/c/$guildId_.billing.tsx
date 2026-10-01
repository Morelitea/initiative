import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import type { BillingPortalPage } from "@/hooks/useBillingPortal";

/**
 * Forwards to the billing portal for one community, for links sent by email.
 *
 * Outside the `$guildId` layout on purpose: that layout serves only
 * communities in the guild list, and one on hold is not in it. The handoff
 * request decides who may go on.
 */
export const Route = createFileRoute("/_serverRequired/_authenticated/c/$guildId_/billing")({
  validateSearch: (search: Record<string, unknown>): { page: BillingPortalPage } => ({
    page: search.page === "upgrade" ? "upgrade" : "manage",
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/BillingForwardPage").then((m) => ({ default: m.BillingForwardPage }))
  ),
});
