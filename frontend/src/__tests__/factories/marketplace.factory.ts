import type {
  MarketplaceListingDetail,
  MarketplaceListingSummary,
  MarketplaceVersionRead,
} from "@/api/generated/initiativeAPI.schemas";

let counter = 0;

export function resetCounter(): void {
  counter = 0;
}

export function buildMarketplaceVersion(
  overrides: Partial<MarketplaceVersionRead> = {}
): MarketplaceVersionRead {
  return {
    version: "1.0.0",
    release_notes: null,
    min_app_version: null,
    published_at: "2026-01-15T00:00:00.000Z",
    compatible: true,
    ...overrides,
  };
}

/**
 * A browse card's listing.
 *
 * Defaults to the shape a shipped listing has — `builtin`, published by
 * Initiative — because that is the one every deployment always has. Pass
 * `source` and `publisher` together to build the non-first-party case:
 * a listing a registry signed, or one an operator added.
 */
export function buildMarketplaceListing(
  overrides: Partial<MarketplaceListingSummary> = {}
): MarketplaceListingSummary {
  counter++;
  return {
    uid: `TESTLISTING${String(counter).padStart(3, "0")}`,
    public_id: `core.listing-${counter}`,
    kind: "dashboard",
    source: "builtin",
    name: `Listing ${counter}`,
    publisher: "Initiative",
    description: "What this listing is for.",
    avatar_url: "/marketplace/test.svg",
    images: [],
    installs_count: 0,
    available: true,
    latest_version: buildMarketplaceVersion(),
    installable: true,
    updated_at: "2026-01-15T00:00:00.000Z",
    ...overrides,
  };
}

export function buildMarketplaceListingDetail(
  overrides: Partial<MarketplaceListingDetail> = {}
): MarketplaceListingDetail {
  const summary = buildMarketplaceListing();
  return {
    ...summary,
    long_description: null,
    definition: null,
    versions: summary.latest_version ? [summary.latest_version] : [],
    ...overrides,
  };
}
