import { beforeEach, describe, expect, it } from "vitest";

import {
  persistCommunityId,
  readStoredCommunityId,
  readStoredCommunityIdFor,
} from "@/lib/activeCommunityStorage";
import { removeItem, setItem } from "@/lib/storage";

const KEY = "initiative-active-guild";

describe("the community a browser remembers", () => {
  beforeEach(() => {
    removeItem(KEY);
  });

  it("keeps one answer per account", () => {
    persistCommunityId(3, 19);
    persistCommunityId(1, 24);

    expect(readStoredCommunityIdFor(19)).toBe(3);
    expect(readStoredCommunityIdFor(24)).toBe(1);
  });

  it("does not answer for an account that has never been here", () => {
    persistCommunityId(3, 19);

    expect(readStoredCommunityIdFor(99)).toBeNull();
  });

  it("offers whoever was here last to code that runs before sign-in", () => {
    persistCommunityId(3, 19);
    persistCommunityId(1, 24);

    expect(readStoredCommunityId()).toBe(1);
  });

  it("reads what the old single-value shape left behind", () => {
    setItem(KEY, "7");

    expect(readStoredCommunityId()).toBe(7);
    // Nothing in that shape says whose it was, so it stands in for any account
    // until the first write under the new one replaces it.
    expect(readStoredCommunityIdFor(19)).toBe(7);

    persistCommunityId(2, 19);
    expect(readStoredCommunityIdFor(19)).toBe(2);
    expect(readStoredCommunityIdFor(24)).toBeNull();
  });

  it("forgets an account's community when it is cleared", () => {
    persistCommunityId(3, 19);
    persistCommunityId(null, 19);

    expect(readStoredCommunityIdFor(19)).toBeNull();
  });

  it("writes nothing when nobody is signed in", () => {
    persistCommunityId(3, null);

    expect(readStoredCommunityId()).toBeNull();
  });
});
