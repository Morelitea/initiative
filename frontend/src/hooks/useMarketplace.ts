/**
 * Reading the marketplace catalog.
 *
 * The catalog is one shared surface addressed by globally unique ids, and no
 * listing carries a guild — but *which* of it a guild is offered does depend on
 * the guild asking: a dashboard an app ships with itself appears only where the
 * app is installed. So every read here is guild-addressed and keyed per guild,
 * the shelf and a single listing alike, and the answer a card gives is the
 * answer the page it opens gives.
 *
 * Whether a listing is *installed here* is a separate per-guild question the
 * dashboards and apps endpoints answer; the surface merges those in client-side.
 */

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  ListMarketplaceListingsApiV1CGuildIdMarketplaceListingsGetParams,
  MarketplaceListingDetail,
  MarketplaceListingPage,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getListMarketplaceListingsApiV1CGuildIdMarketplaceListingsGetQueryKey,
  getReadMarketplaceListingApiV1CGuildIdMarketplaceListingsPublicIdGetQueryKey,
  getResolveMarketplaceListingApiV1CGuildIdMarketplaceListingsByUidUidGetQueryKey,
  listMarketplaceListingsApiV1CGuildIdMarketplaceListingsGet,
  readMarketplaceListingApiV1CGuildIdMarketplaceListingsPublicIdGet,
  resolveMarketplaceListingApiV1CGuildIdMarketplaceListingsByUidUidGet,
} from "@/api/generated/marketplace/marketplace";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";
import type { QueryOpts } from "@/types/query";

/** The catalog changes when a deployment is upgraded or a registry refresh
 *  runs, not while someone is browsing. */
const CATALOG_STALE_MS = 5 * 60 * 1000;

export const useMarketplaceListings = (
  params?: ListMarketplaceListingsApiV1CGuildIdMarketplaceListingsGetParams,
  options?: QueryOpts<MarketplaceListingPage>
) => {
  const guildId = useActiveGuildId();
  return useQuery<MarketplaceListingPage>({
    queryKey: getListMarketplaceListingsApiV1CGuildIdMarketplaceListingsGetQueryKey(
      guildId,
      params
    ),
    queryFn: () => listMarketplaceListingsApiV1CGuildIdMarketplaceListingsGet(guildId, params),
    // Typing keeps the previous page on screen while the next one loads, so the
    // grid does not blank out on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: CATALOG_STALE_MS,
    ...options,
  });
};

export const useMarketplaceListing = (
  publicId: string | null,
  options?: QueryOpts<MarketplaceListingDetail>
) => {
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MarketplaceListingDetail>({
    queryKey: getReadMarketplaceListingApiV1CGuildIdMarketplaceListingsPublicIdGetQueryKey(
      guildId,
      publicId ?? ""
    ),
    queryFn: () =>
      readMarketplaceListingApiV1CGuildIdMarketplaceListingsPublicIdGet(
        guildId,
        publicId as string
      ),
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
  const guildId = useActiveGuildId();
  const { enabled: userEnabled = true, ...rest } = options ?? {};
  return useQuery<MarketplaceListingDetail>({
    queryKey: getResolveMarketplaceListingApiV1CGuildIdMarketplaceListingsByUidUidGetQueryKey(
      guildId,
      uid ?? ""
    ),
    queryFn: () =>
      resolveMarketplaceListingApiV1CGuildIdMarketplaceListingsByUidUidGet(guildId, uid as string),
    enabled: Boolean(uid) && userEnabled,
    staleTime: CATALOG_STALE_MS,
    // A listing this guild cannot take is a real answer for an installed
    // dashboard — withdrawn, or an app it no longer has — not something to
    // retry.
    retry: false,
    ...rest,
  });
};
