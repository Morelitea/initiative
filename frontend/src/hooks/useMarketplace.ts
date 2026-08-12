/**
 * Reading the marketplace catalog.
 *
 * The catalog is platform-level: one shared surface, addressed by globally
 * unique ids, with no guild in the request or the response. So these queries are
 * keyed on what was asked for and nothing else, and two guilds browsing the same
 * deployment share one cache entry.
 *
 * Whether a listing is *installed here* is a per-guild question the dashboards
 * endpoints answer; the surface merges the two client-side rather than asking
 * the catalog something it does not know.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  ListMarketplaceListingsApiV1MarketplaceListingsGetParams,
  MarketplaceListingDetail,
  MarketplaceListingPage,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListMarketplaceListingsApiV1MarketplaceListingsGetQueryKey,
  getReadMarketplaceListingApiV1MarketplaceListingsPublicIdGetQueryKey,
  getResolveMarketplaceListingApiV1MarketplaceListingsByUidUidGetQueryKey,
  listMarketplaceListingsApiV1MarketplaceListingsGet,
  readMarketplaceListingApiV1MarketplaceListingsPublicIdGet,
  resolveMarketplaceListingApiV1MarketplaceListingsByUidUidGet,
} from "@/api/generated/marketplace/marketplace";
import type { QueryOpts } from "@/types/query";

/** The catalog changes when a deployment is upgraded or a registry refresh
 *  runs, not while someone is browsing. */
const CATALOG_STALE_MS = 5 * 60 * 1000;

export const useMarketplaceListings = (
  params?: ListMarketplaceListingsApiV1MarketplaceListingsGetParams,
  options?: QueryOpts<MarketplaceListingPage>
) =>
  useQuery<MarketplaceListingPage>({
    queryKey: getListMarketplaceListingsApiV1MarketplaceListingsGetQueryKey(params),
    queryFn: () => listMarketplaceListingsApiV1MarketplaceListingsGet(params),
    // Typing keeps the previous page on screen while the next one loads, so the
    // grid does not blank out on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: CATALOG_STALE_MS,
    ...options,
  });

export const useMarketplaceListing = (
  publicId: string | null,
  options?: QueryOpts<MarketplaceListingDetail>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MarketplaceListingDetail>({
    queryKey: getReadMarketplaceListingApiV1MarketplaceListingsPublicIdGetQueryKey(publicId ?? ""),
    queryFn: () => readMarketplaceListingApiV1MarketplaceListingsPublicIdGet(publicId as string),
    enabled: Boolean(publicId) && userEnabled,
    staleTime: CATALOG_STALE_MS,
    ...rest,
  });
};

/**
 * The listing behind an installed instance.
 *
 * An install stores its listing's uid, not its public id — the uid is the stable
 * identity across deployments — so finding "where did this come from, and is
 * there a newer version?" goes through the uid.
 */
export const useMarketplaceListingByUid = (
  uid: string | null | undefined,
  options?: QueryOpts<MarketplaceListingDetail>
) => {
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MarketplaceListingDetail>({
    queryKey: getResolveMarketplaceListingApiV1MarketplaceListingsByUidUidGetQueryKey(uid ?? ""),
    queryFn: () => resolveMarketplaceListingApiV1MarketplaceListingsByUidUidGet(uid as string),
    enabled: Boolean(uid) && userEnabled,
    staleTime: CATALOG_STALE_MS,
    // A listing can be withdrawn; that is a real answer for an installed
    // dashboard, not something to retry.
    retry: false,
    ...rest,
  });
};
