/**
 * What counts as a page in this app, for the three readers of `next`.
 */
import { describe, expect, it } from "vitest";

import { returnPath } from "@/lib/returnPath";

describe("the page a sign-in returns to", () => {
  it("keeps a path in this app, query and fragment and all", () => {
    expect(returnPath("/profile/security")).toBe("/profile/security");
    expect(returnPath("/c/1/search?q=riverside#top")).toBe("/c/1/search?q=riverside#top");
  });

  it("has nothing for anywhere else", () => {
    expect(returnPath("//example.test/take-me")).toBeNull();
    expect(returnPath("/\\example.test/take-me")).toBeNull();
    expect(returnPath("https://example.test/take-me")).toBeNull();
    expect(returnPath("profile/security")).toBeNull();
  });

  it("has nothing when there was no trip to finish", () => {
    expect(returnPath(undefined)).toBeNull();
    expect(returnPath(null)).toBeNull();
    expect(returnPath("")).toBeNull();
  });
});
