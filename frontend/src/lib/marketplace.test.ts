import { describe, expect, it } from "vitest";

import { ListingKind } from "@/api/generated/initiativeAPI.schemas";

import { COMMUNITY_SHELVES, isUserShelf, USER_SHELVES } from "./marketplace";

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
