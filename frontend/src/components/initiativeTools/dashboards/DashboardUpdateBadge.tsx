/**
 * "There's a newer version of this."
 *
 * Shown only for a dashboard that was installed from a listing, and only when
 * the version it is pinned to is not the one the listing currently publishes.
 * Taking it is always a click: applying a new version replaces this dashboard's
 * canvas, so it is the author's call and nobody else's — and it re-pins this
 * dashboard alone, leaving any other install of the same listing where it is.
 *
 * A dashboard authored here has no listing and renders nothing at all.
 */

import { ArrowUpCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { DashboardRead } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import { useUpgradeDashboard } from "@/hooks/useDashboards";
import { useMarketplaceListingByUid } from "@/hooks/useMarketplace";
import { toast } from "@/lib/chesterToast";
import { getErrorMessage } from "@/lib/errorMessage";

export interface DashboardUpdateBadgeProps {
  dashboard: DashboardRead;
  /** Applying a version rewrites the canvas, so it takes the same write access
   *  that editing does. Without it the badge is informational. */
  canEdit: boolean;
}

export function DashboardUpdateBadge({ dashboard, canEdit }: DashboardUpdateBadgeProps) {
  const { t } = useTranslation("marketplace");
  const listingQuery = useMarketplaceListingByUid(dashboard.listing_uid);
  const upgrade = useUpgradeDashboard(dashboard.id);

  const latest = listingQuery.data?.latest_version;
  // Nothing to offer: not installed, the listing is gone, this build cannot run
  // the new version, or it is already the pinned one.
  if (!latest?.compatible || latest.version === dashboard.listing_version) {
    return null;
  }

  const apply = () =>
    upgrade.mutate(undefined, {
      onSuccess: (updated) => {
        toast.success(t("update.done", { version: updated.listing_version }));
      },
      onError: (error) => {
        toast.error(getErrorMessage(error, "marketplace:update.failed"));
      },
    });

  if (!canEdit) {
    return (
      <span className="text-muted-foreground text-xs">
        {t("update.available", { version: latest.version })}
      </span>
    );
  }

  return (
    <Button size="sm" variant="outline" onClick={apply} disabled={upgrade.isPending}>
      {upgrade.isPending ? (
        <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
      ) : (
        <ArrowUpCircle className="mr-1.5 h-4 w-4" />
      )}
      {t("update.available", { version: latest.version })}
    </Button>
  );
}
