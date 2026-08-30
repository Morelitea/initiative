/**
 * The marketplace, as a place you browse.
 *
 * A searchable card grid rather than a menu: listings are products with artwork,
 * an author, and a description, and picking one is a decision worth a page.
 *
 * The shelf is guild-addressed: a dashboard an app ships with itself appears
 * only where the app is installed, so the catalog is asked on this guild's
 * behalf. What is already installed here is a second question, answered by the
 * guild's own dashboards and apps lists and matched up client-side.
 */

import { useSearch } from "@tanstack/react-router";
import { CloudOff, SearchX } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";
import { MarketplaceCard } from "@/components/marketplace/MarketplaceCard";
import { StatusMessage } from "@/components/StatusMessage";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useInstalledListings } from "@/hooks/useDashboards";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useGuildApps } from "@/hooks/useGuildApps";
import { useMarketplaceListings } from "@/hooks/useMarketplace";

const PAGE_SIZE = 24;
/** One line per shelf, so a new kind shows its own rather than the dashboards'. */
const SUBTITLE_KEYS = {
  [ListingKind.dashboard]: "subtitle",
  [ListingKind.app]: "subtitleApps",
  [ListingKind.auto]: "subtitleAuto",
} as const;
/** Stable keys for the loading placeholders — they never reorder, and an index
 *  key on a list that can change is the lint rule this avoids. */
const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export function MarketplaceBrowsePage() {
  const { t } = useTranslation("marketplace");
  // Which shelf: dashboards, or the apps a guild admin adds.
  //
  // Defaulted here, not left to the route. `useSearch({ strict: false })` reads
  // the params as they are — it does not run the route's `validateSearch` — so
  // relying on that default would mean the filter silently disappears anywhere
  // the page is mounted another way, and the grid would mix apps into the
  // dashboards.
  const search_ = useSearch({ strict: false }) as { kind?: ListingKind };
  const kind = search_.kind ?? ListingKind.dashboard;
  const [query, setQuery] = useState("");
  // The catalog is a network call per keystroke otherwise, and the grid keeps
  // the previous page while the next one loads.
  const search = useDebouncedValue(query, 250);

  const listingsQuery = useMarketplaceListings({
    kind,
    q: search.trim() || undefined,
    page_size: PAGE_SIZE,
  });

  // Which of these this guild already has. Each shelf has to ask its own tool:
  // the dashboards aggregate knows nothing about apps, so using it on the apps
  // shelf would report every app as not installed.
  //
  // Left undefined when the request failed, rather than defaulted to an empty
  // map: "we do not know" and "you have none of these" look identical on a card,
  // and only one of them is true. The notice below says which.
  const dashboardInstalls = useInstalledListings({ enabled: kind === ListingKind.dashboard });
  const appInstalls = useGuildApps({ enabled: kind === ListingKind.app });
  const installedQuery = kind === ListingKind.app ? appInstalls : dashboardInstalls;

  const installedByUid = useMemo(() => {
    if (installedQuery.isError) return undefined;
    if (kind === ListingKind.app) {
      // One install per listing per guild, so this is a presence map that
      // happens to be shaped like the dashboards' counts.
      const counts: Record<string, number> = {};
      for (const app of appInstalls.data?.items ?? []) counts[app.listing_uid] = 1;
      return counts;
    }
    return dashboardInstalls.data?.counts;
  }, [kind, installedQuery.isError, appInstalls.data, dashboardInstalls.data]);

  const listings = listingsQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="font-semibold text-3xl tracking-tight">{t("title")}</h1>
        <p className="text-muted-foreground text-sm">{t(SUBTITLE_KEYS[kind])}</p>
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
