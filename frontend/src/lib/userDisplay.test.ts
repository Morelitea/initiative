import { describe, expect, it } from "vitest";

import {
  formatDiscriminator,
  getUserDisplayName,
  getUserHandle,
  hasDisplayName,
  isInactiveUser,
} from "@/lib/userDisplay";
import { slugifyUsername } from "@/lib/usernames";

const withHandle = { id: 7, username: "foobar", discriminator: 12 };

describe("getUserHandle", () => {
  it("writes the number as four digits", () => {
    expect(getUserHandle(withHandle)).toBe("foobar#0012");
    expect(getUserHandle({ ...withHandle, discriminator: 1234 })).toBe("foobar#1234");
    expect(getUserHandle({ ...withHandle, discriminator: 0 })).toBe("foobar#0000");
  });

  it("has nothing to write without a name part", () => {
    expect(getUserHandle({ id: 7 })).toBe("");
    expect(getUserHandle(null)).toBe("");
  });
});

describe("formatDiscriminator", () => {
  it("pads, and says nothing about a missing number", () => {
    expect(formatDiscriminator(12)).toBe("0012");
    expect(formatDiscriminator(null)).toBe("");
  });
});

describe("getUserDisplayName", () => {
  it("prefers a name the guild sent", () => {
    expect(getUserDisplayName({ ...withHandle, full_name: "Jordan Drako" })).toBe("Jordan Drako");
  });

  it("falls back to the handle", () => {
    // A guild that shows handles sends no name at all, so this is the ordinary
    // case rather than an edge one.
    expect(getUserDisplayName(withHandle)).toBe("foobar#0012");
    expect(getUserDisplayName({ ...withHandle, full_name: "   " })).toBe("foobar#0012");
  });

  it("keeps rendering the handle for an account no longer in use", () => {
    // The handle is a pseudonym and a unique identifier at once — an old
    // thread stays legible only if it survives the account.
    expect(getUserDisplayName({ ...withHandle, status: "anonymized" })).toBe("foobar#0012");
    expect(getUserDisplayName({ ...withHandle, status: "deactivated" })).toBe("foobar#0012");
  });

  it("leaves an unresolved id to the caller's placeholder", () => {
    expect(getUserDisplayName({ id: 42 }, "User #42")).toBe("User #42");
    expect(getUserDisplayName(null, "User")).toBe("User");
  });
});

describe("isInactiveUser", () => {
  it("covers both ways an account stops being used", () => {
    expect(isInactiveUser({ ...withHandle, status: "active" })).toBe(false);
    expect(isInactiveUser({ ...withHandle, status: "deactivated" })).toBe(true);
    expect(isInactiveUser({ ...withHandle, status: "anonymized" })).toBe(true);
  });
});

describe("hasDisplayName", () => {
  it("is true as soon as there is a handle", () => {
    expect(hasDisplayName(withHandle)).toBe(true);
    expect(hasDisplayName({ id: 7 })).toBe(false);
  });
});

describe("slugifyUsername", () => {
  it("offers first initial and last name, as the server seeds", () => {
    expect(slugifyUsername("Lee Janzen")).toBe("ljanzen");
    expect(slugifyUsername("Ada Lovelace King")).toBe("aking");
    expect(slugifyUsername("Élodie Martin")).toBe("emartin");
  });

  it("lets a single-word name stand on its own", () => {
    expect(slugifyUsername("Jordan")).toBe("jordan");
    expect(slugifyUsername("  Jordan  ")).toBe("jordan");
  });

  it("offers nothing for an address", () => {
    // An address is never the source of a handle, here or on the server.
    expect(slugifyUsername("jordan@example.com")).toBe("");
  });

  it("offers nothing when too little survives", () => {
    expect(slugifyUsername("")).toBe("");
    expect(slugifyUsername("!!")).toBe("");
    expect(slugifyUsername("Jo")).toBe("");
  });
});
