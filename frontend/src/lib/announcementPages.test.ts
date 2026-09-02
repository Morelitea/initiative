import { describe, expect, it } from "vitest";

import type { AnnouncementSection } from "@/api/generated/initiativeAPI.schemas";

import { matchesTriggerRoute, splitIntoPages, validateTriggerRoute } from "./announcementPages";

const section = (heading: string, startsPage = false): AnnouncementSection => ({
  heading,
  starts_page: startsPage,
});

describe("splitIntoPages", () => {
  it("keeps an unbroken list as a single page", () => {
    const pages = splitIntoPages([section("a"), section("b")]);
    expect(pages).toHaveLength(1);
    expect(pages[0]).toHaveLength(2);
  });

  it("breaks where a section says so", () => {
    const pages = splitIntoPages([section("a"), section("b", true), section("c")]);
    expect(pages.map((page) => page.map((s) => s.heading))).toEqual([["a"], ["b", "c"]]);
  });

  it("does not open with an empty page when the first section breaks", () => {
    const pages = splitIntoPages([section("a", true), section("b")]);
    expect(pages.map((page) => page.map((s) => s.heading))).toEqual([["a", "b"]]);
  });

  it("has no pages when there are no sections", () => {
    expect(splitIntoPages([])).toEqual([]);
  });
});

describe("matchesTriggerRoute", () => {
  it("matches an exact path", () => {
    expect(matchesTriggerRoute("/settings/admin", "/settings/admin")).toBe(true);
    expect(matchesTriggerRoute("/settings/admin", "/settings")).toBe(false);
  });

  it("ignores a trailing slash on either side", () => {
    expect(matchesTriggerRoute("/settings/", "/settings")).toBe(true);
    expect(matchesTriggerRoute("/settings", "/settings/")).toBe(true);
  });

  it("treats * as exactly one segment", () => {
    expect(matchesTriggerRoute("/c/*/settings", "/c/12/settings")).toBe(true);
    expect(matchesTriggerRoute("/c/*/settings", "/c/12/34/settings")).toBe(false);
    expect(matchesTriggerRoute("/c/*/settings", "/c/12/settings/users")).toBe(false);
  });

  it("treats ** as the rest of the path, including none of it", () => {
    expect(matchesTriggerRoute("/c/**", "/c/12/i/3/projects/9")).toBe(true);
    expect(matchesTriggerRoute("/c/**", "/c")).toBe(true);
    expect(matchesTriggerRoute("/c/**", "/settings")).toBe(false);
  });

  it("combines the two wildcards", () => {
    expect(matchesTriggerRoute("/c/*/i/*/projects/**", "/c/1/i/2/projects/3/tasks/4")).toBe(true);
    expect(matchesTriggerRoute("/c/*/i/*/projects/**", "/c/1/i/2/documents/3")).toBe(false);
  });
});

describe("validateTriggerRoute", () => {
  it("accepts an empty field — the trigger is optional", () => {
    expect(validateTriggerRoute("")).toBeNull();
    expect(validateTriggerRoute("   ")).toBeNull();
  });

  it("accepts the patterns the matcher understands", () => {
    expect(validateTriggerRoute("/settings/admin")).toBeNull();
    expect(validateTriggerRoute("/c/*/settings")).toBeNull();
    expect(validateTriggerRoute("/c/*/i/*/projects/**")).toBeNull();
  });

  it("catches a missing leading slash", () => {
    expect(validateTriggerRoute("c/*/settings")).toBe("needsSlash");
    expect(validateTriggerRoute("https://example.test/x")).toBe("needsSlash");
    expect(validateTriggerRoute("//example.test/x")).toBe("needsSlash");
  });

  it("catches spaces", () => {
    expect(validateTriggerRoute("/c/* /settings")).toBe("whitespace");
  });

  it("catches a wildcard glued to a segment, which could never match", () => {
    expect(validateTriggerRoute("/c/*settings")).toBe("wildcardSegment");
    expect(validateTriggerRoute("/c/**/x**")).toBe("wildcardSegment");
  });

  it("catches anything written after **", () => {
    expect(validateTriggerRoute("/c/**/settings")).toBe("doubleStarNotLast");
  });
});
