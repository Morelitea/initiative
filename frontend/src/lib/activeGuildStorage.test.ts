import { beforeEach, describe, expect, it } from "vitest";

import { persistGuildId, readStoredGuildId, readStoredGuildIdFor } from "@/lib/activeGuildStorage";
import { removeItem, setItem } from "@/lib/storage";

const KEY = "initiative-active-guild";

describe("the community a browser remembers", () => {
  beforeEach(() => {
    removeItem(KEY);
  });

  it("keeps one answer per account", () => {
    persistGuildId(3, 19);
    persistGuildId(1, 24);

    expect(readStoredGuildIdFor(19)).toBe(3);
    expect(readStoredGuildIdFor(24)).toBe(1);
  });

  it("does not answer for an account that has never been here", () => {
    persistGuildId(3, 19);

    expect(readStoredGuildIdFor(99)).toBeNull();
  });

  it("offers whoever was here last to code that runs before sign-in", () => {
    persistGuildId(3, 19);
    persistGuildId(1, 24);

    expect(readStoredGuildId()).toBe(1);
  });

  it("reads what the old single-value shape left behind", () => {
    setItem(KEY, "7");

    expect(readStoredGuildId()).toBe(7);
    // Nothing in that shape says whose it was, so it stands in for any account
    // until the first write under the new one replaces it.
    expect(readStoredGuildIdFor(19)).toBe(7);

    persistGuildId(2, 19);
    expect(readStoredGuildIdFor(19)).toBe(2);
    expect(readStoredGuildIdFor(24)).toBeNull();
  });

  it("forgets an account's community when it is cleared", () => {
    persistGuildId(3, 19);
    persistGuildId(null, 19);

    expect(readStoredGuildIdFor(19)).toBeNull();
  });

  it("writes nothing when nobody is signed in", () => {
    persistGuildId(3, null);

    expect(readStoredGuildId()).toBeNull();
  });
});
