import { describe, expect, it, vi } from "vitest";

// Stub the i18n module so the policy returns its lookup key — we can
// then assert on which key was requested without booting i18next.
vi.mock("@/i18n", () => ({
  default: { t: (key: string) => key },
}));

import { checkNewPassword, PASSWORD_MIN_LENGTH } from "./passwordPolicy";

describe("checkNewPassword", () => {
  it("asks for a matching confirmation before anything else", () => {
    expect(checkNewPassword("a".repeat(PASSWORD_MIN_LENGTH), "b")).toBe(
      "auth:passwordPolicy.mismatch"
    );
    expect(checkNewPassword("short", "other")).toBe("auth:passwordPolicy.mismatch");
  });

  it("flags a matching pair one character shorter than the minimum", () => {
    const password = "a".repeat(PASSWORD_MIN_LENGTH - 1);
    expect(checkNewPassword(password, password)).toBe("auth:passwordPolicy.minLength");
  });

  it("accepts a matching pair at exactly the minimum length", () => {
    const password = "a".repeat(PASSWORD_MIN_LENGTH);
    expect(checkNewPassword(password, password)).toBeNull();
  });

  it("accepts a long password regardless of character classes", () => {
    // Mirror of the NIST 800-63B stance: no class requirements client-side.
    expect(
      checkNewPassword("correct-horse-battery-staple", "correct-horse-battery-staple")
    ).toBeNull();
    expect(checkNewPassword("all-lowercase-passphrase", "all-lowercase-passphrase")).toBeNull();
  });
});
