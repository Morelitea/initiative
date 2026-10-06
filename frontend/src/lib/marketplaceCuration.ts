/**
 * Which marketplace listings this app shows and installs.
 *
 * The iPhone app offers only the curated catalogue: listings shipped in this
 * build (`builtin`) and listings from the signed registry (`registry`). Listings
 * a server's operator or members added are left out there. Every other
 * platform shows the whole catalogue.
 *
 * Apps a community has already installed are not affected — the community chose
 * them — but the iPhone app shows a notice the first time a member opens one
 * that did not ship with Initiative (see `AppProviderNotice`).
 */

import { Capacitor } from "@capacitor/core";

import { ListingSource } from "@/api/generated/initiativeAPI.schemas";

/** The sources the curated catalogue is made of. */
export const CURATED_SOURCE_LIST: ListingSource[] = [ListingSource.builtin, ListingSource.registry];

const CURATED_SOURCES: ReadonlySet<string> = new Set<string>(CURATED_SOURCE_LIST);

/** Whether a listing from `source` is part of the curated catalogue. */
export const isCuratedSource = (source: string | null | undefined): boolean =>
  source != null && CURATED_SOURCES.has(source);

/** Whether this app shows only the curated catalogue. */
export const showsCuratedCatalogueOnly = (): boolean => Capacitor.getPlatform() === "ios";

/** The sources to ask the catalogue for here, or undefined for all of them. */
export const catalogueSources = (): ListingSource[] | undefined =>
  showsCuratedCatalogueOnly() ? CURATED_SOURCE_LIST : undefined;

/** Whether `listing` is shown, and may be installed, in this app. */
export const listingShownHere = (listing: { source: string }): boolean =>
  !showsCuratedCatalogueOnly() || isCuratedSource(listing.source);
