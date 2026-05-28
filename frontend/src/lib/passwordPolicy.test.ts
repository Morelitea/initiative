import { describe, expect, it, vi } from "vitest";

// Stub the i18n module so the policy returns its lookup key — we can
// then assert on which key was requested without booting i18next.
vi.mock("@/i18n", () => ({
  default: { t: (key: string) => key },
}));

import { PASSWORD_MIN_LENGTH, validatePasswordLocal } from "./passwordPolicy";

describe("validatePasswordLocal", () => {
  it("returns null for the empty string so we don't shout before typing", () => {
    expect(validatePasswordLocal("")).toBeNull();
  });

  it("flags a password one character shorter than the minimum", () => {
    const password = "a".repeat(PASSWORD_MIN_LENGTH - 1);
    expect(validatePasswordLocal(password)).toBe("auth:passwordPolicy.minLength");
  });

  it("accepts a password at exactly the minimum length", () => {
    const password = "a".repeat(PASSWORD_MIN_LENGTH);
    expect(validatePasswordLocal(password)).toBeNull();
  });

  it("accepts a long password regardless of character classes", () => {
    // Mirror of the NIST 800-63B stance: no class requirements client-side.
    expect(validatePasswordLocal("correct-horse-battery-staple")).toBeNull();
    expect(validatePasswordLocal("all-lowercase-passphrase")).toBeNull();
  });
});
