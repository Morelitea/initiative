/**
 * The marketplace, as a place you browse.
 *
 * A searchable card grid rather than a menu: listings are products with artwork,
 * a publisher, and a description, and picking one is a decision worth a page.
 *
 * The catalog is platform-level, so this asks it nothing about this guild. What
 * is already installed here comes from the guild's own dashboards list and is
 * matched up client-side.
 */

import { SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { MarketplaceCard } from "@/components/marketplace/MarketplaceCard";
import { StatusMessage } from "@/components/StatusMessage";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboardsList } from "@/hooks/useDashboards";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useMarketplaceListings } from "@/hooks/useMarketplace";

const PAGE_SIZE = 24;
/** Stable keys for the loading placeholders — they never reorder, and an index
 *  key on a list that can change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function MarketplaceBrowsePage() {
  const { t } = useTranslation("marketplace");
  const [query, setQuery] = useState("");
  // The catalog is a network call per keystroke otherwise, and the grid keeps
  // the previous page while the next one loads.
  const search = useDebouncedValue(query, 250);

  const listingsQuery = useMarketplaceListings({
    kind: "dashboard",
    q: search.trim() || undefined,
    page_size: PAGE_SIZE,
  });

  // Which of these this guild already has. A count, not a boolean: a guild may
  // hold several installs of one listing, at different versions.
  const dashboardsQuery = useDashboardsList();
  const installedByUid = useMemo(() => {
    const counts = new Map<string, number>();
    for (const dashboard of dashboardsQuery.data?.items ?? []) {
      if (!dashboard.listing_uid) continue;
      counts.set(dashboard.listing_uid, (counts.get(dashboard.listing_uid) ?? 0) + 1);
    }
    return counts;
  }, [dashboardsQuery.data]);

  const listings = listingsQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t("subtitle")}</p>
      </div>

      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        className="max-w-md"
      />

      {listingsQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      ) : listings.length ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {listings.map((listing) => (
            <MarketplaceCard
              key={listing.public_id}
              listing={listing}
              installedCount={installedByUid.get(listing.uid) ?? 0}
            />
          ))}
        </div>
      ) : (
        <StatusMessage
          icon={<SearchX />}
          title={search ? t("noResults.title") : t("empty.title")}
          description={
            search ? t("noResults.description", { query: search }) : t("empty.description")
          }
        />
      )}
    </div>
  );
}
