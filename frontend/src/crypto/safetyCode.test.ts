import { describe, expect, it } from "vitest";

import { SAFETY_CODE_LENGTH, safetyCode } from "./safetyCode";

/** A real Ed25519 key, as the directory writes one. */
const KEY = "C35J1oMcLovDN1JgJEHVuok+7W313W52YY6oaGnw2m8=";

describe("a device key as pictures", () => {
  it("draws the same code for the same key, on both screens", () => {
    expect(safetyCode(KEY)).toEqual(safetyCode(KEY));
    expect(safetyCode(KEY)).toHaveLength(SAFETY_CODE_LENGTH);
  });

  it("walks the key the way the other end will", () => {
    // A fixed vector: the pictures are six-bit groups read off the front of the
    // decoded key, most significant bit first. Two implementations that walk it
    // differently agree on nothing, and this is what says which walk is ours.
    expect(safetyCode(KEY).map((entry) => entry.name)).toEqual([
      "lion",
      "trophy",
      "guitar",
      "rooster",
      "aeroplane",
      "gift",
    ]);
  });

  it("draws a different code for a different key", () => {
    const other = "zuFDxA+kaChnPNa1QI59q0xuKG+kAI21A/AGDod1RPM=";
    expect(safetyCode(other)).not.toEqual(safetyCode(KEY));
  });

  it("is decided by the front of the key, so a swapped key looks wrong at once", () => {
    // The same key with its first character changed. Six pictures cannot cover
    // all 32 bytes, so what matters is where they are read from: whoever is
    // comparing reads left to right, and a key that differs at the front should
    // be wrong in the first picture rather than the last.
    const early = "D35J1oMcLovDN1JgJEHVuok+7W313W52YY6oaGnw2m8=";
    expect(safetyCode(early)[0]).not.toEqual(safetyCode(KEY)[0]);
  });

  it("names every picture it draws", () => {
    for (const entry of safetyCode(KEY)) {
      expect(entry.emoji).toBeTruthy();
      expect(entry.name).toMatch(/^[a-zA-Z]+$/);
    }
  });

  it("draws a code for a key that is not base64 rather than none at all", () => {
    // Nothing writes one — but a code that cannot be drawn is a comparison
    // nobody can make, which is worse than one drawn from the characters.
    expect(safetyCode("not a key")).toHaveLength(SAFETY_CODE_LENGTH);
  });

  it("has nothing to draw for an empty key", () => {
    expect(safetyCode("")).toEqual([]);
  });
});
