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

import { useSearch } from "@tanstack/react-router";
import { CloudOff, SearchX } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { MarketplaceCard } from "@/components/marketplace/MarketplaceCard";
import { StatusMessage } from "@/components/StatusMessage";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useInstalledListings } from "@/hooks/useDashboards";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useMarketplaceListings } from "@/hooks/useMarketplace";

const PAGE_SIZE = 24;
/** Stable keys for the loading placeholders — they never reorder, and an index
 *  key on a list that can change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function MarketplaceBrowsePage() {
  const { t } = useTranslation("marketplace");
  // Which shelf: dashboards, or the apps a guild admin adds. The route
  // normalizes anything unexpected back to dashboards.
  const { kind } = useSearch({ strict: false }) as { kind?: "dashboard" | "app" };
  const [query, setQuery] = useState("");
  // The catalog is a network call per keystroke otherwise, and the grid keeps
  // the previous page while the next one loads.
  const search = useDebouncedValue(query, 250);

  const listingsQuery = useMarketplaceListings({
    kind,
    q: search.trim() || undefined,
    page_size: PAGE_SIZE,
  });

  // Which of these this guild already has, counted server-side over every
  // dashboard rather than over a page of them. A count, not a boolean: a guild
  // may hold several installs of one listing, at different versions.
  //
  // Left undefined when that request failed, rather than defaulted to an empty
  // map: "we do not know" and "you have none of these" look identical on a card,
  // and only one of them is true. The notice below says which.
  const installedQuery = useInstalledListings();
  const installedByUid = installedQuery.isError ? undefined : installedQuery.data?.counts;

  const listings = listingsQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">
          {kind === "app" ? t("subtitleApps") : t("subtitle")}
        </p>
      </div>

      <Input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t("searchPlaceholder")}
        aria-label={t("searchPlaceholder")}
        className="max-w-md"
      />

      {listingsQuery.isError ? (
        // A catalog that failed to answer is not a catalog with nothing in it,
        // and saying so would send someone looking for listings that exist.
        <StatusMessage
          icon={<CloudOff />}
          title={t("unavailable.title")}
          description={t("unavailable.description")}
        />
      ) : listingsQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      ) : listings.length ? (
        <>
          {installedQuery.isError && (
            <p className="text-muted-foreground text-sm">{t("installedUnknown")}</p>
          )}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {listings.map((listing) => (
              <MarketplaceCard
                key={listing.public_id}
                listing={listing}
                installedCount={installedByUid?.[listing.uid] ?? 0}
              />
            ))}
          </div>
        </>
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
