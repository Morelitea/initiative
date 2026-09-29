import { describe, expect, it } from "vitest";

import { accountSafetyNumber, DEVICE_CODE_LENGTH, deviceCode } from "./safetyCode";

/** Real Ed25519 and Curve25519 keys, as the directory writes them. */
const KEYS = {
  fingerprintKey: "C35J1oMcLovDN1JgJEHVuok+7W313W52YY6oaGnw2m8=",
  identityKey: "zuFDxA+kaChnPNa1QI59q0xuKG+kAI21A/AGDod1RPM=",
};
const SWAPPED = { fingerprintKey: KEYS.identityKey, identityKey: KEYS.fingerprintKey };

describe("a device as pictures", () => {
  it("walks the stretched digest the way the other end will", async () => {
    // Fixed vectors, worked out independently of this code: two
    // implementations that stretch or walk it differently agree on nothing,
    // and this is what says which way is ours.
    const code = await deviceCode(7, KEYS);
    expect(code).toHaveLength(DEVICE_CODE_LENGTH);
    expect(code.map((entry) => entry.name)).toEqual([
      "hourglass",
      "pizza",
      "key",
      "lightBulb",
      "gift",
      "book",
      "heart",
      "mushroom",
      "anchor",
      "umbrella",
    ]);
    // The account is part of it: the same keys listed under somebody else draw
    // a different code.
    expect((await deviceCode(8, KEYS)).map((entry) => entry.name)).toEqual([
      "book",
      "lion",
      "cat",
      "aeroplane",
      "butterfly",
      "rabbit",
      "moon",
      "hammer",
      "butterfly",
      "dog",
    ]);
  });
});

describe("an account's half of a safety number", () => {
  it("is thirty digits over every device, whatever order they are listed in", async () => {
    expect(await accountSafetyNumber(7, [KEYS])).toBe("270021118579113435432062759977");
    const both = "543177903823045855530299665291";
    expect(await accountSafetyNumber(7, [SWAPPED, KEYS])).toBe(both);
    expect(await accountSafetyNumber(7, [KEYS, SWAPPED])).toBe(both);
  });
});
