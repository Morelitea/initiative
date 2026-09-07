import { describe, expect, it } from "vitest";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

import {
  COMMUNITY_SHELVES,
  DEFAULT_COMMUNITY_SHELF,
  isUserShelf,
  parseCommunityShelf,
  parseListingKind,
  USER_SHELVES,
} from "./marketplace";

describe("who a listing is offered to", () => {
  it("places every kind the server knows on exactly one shelf", () => {
    // A kind added server-side and missed here would be offered by neither
    // marketplace — invisible rather than obviously broken.
    const placed = [...USER_SHELVES, ...COMMUNITY_SHELVES];
    expect(new Set(placed).size).toBe(placed.length);
    expect(new Set(placed)).toEqual(new Set(Object.values(ListingKind)));
  });

  it("sells a profile pack to a person", () => {
    expect(isUserShelf(ListingKind.profile_pack)).toBe(true);
    expect(isUserShelf(ListingKind.dashboard)).toBe(false);
  });
});

describe("reading a kind out of the URL", () => {
  it("accepts every kind the server publishes", () => {
    for (const kind of Object.values(ListingKind)) {
      expect(parseListingKind(kind)).toBe(kind);
    }
  });

  it("reports nothing for a kind that is not one", () => {
    expect(parseListingKind("dashboards")).toBeUndefined();
    expect(parseListingKind(undefined)).toBeUndefined();
    expect(parseListingKind(7)).toBeUndefined();
  });

  it("opens each community shelf the URL names", () => {
    for (const shelf of COMMUNITY_SHELVES) {
      expect(parseCommunityShelf(shelf)).toBe(shelf);
    }
  });

  it("falls back to the default shelf for anything a community does not sell", () => {
    // A person's shelf reached through a community URL is not that community's,
    // and neither is a typo or an absent param.
    expect(parseCommunityShelf(ListingKind.profile_pack)).toBe(DEFAULT_COMMUNITY_SHELF);
    expect(parseCommunityShelf("nonsense")).toBe(DEFAULT_COMMUNITY_SHELF);
    expect(parseCommunityShelf(undefined)).toBe(DEFAULT_COMMUNITY_SHELF);
  });

  it("defaults to a shelf the community actually has", () => {
    expect(COMMUNITY_SHELVES).toContain(DEFAULT_COMMUNITY_SHELF);
  });
});
