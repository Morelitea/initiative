/**
 * A detail page reads its initiative from the path, but the entity it loads is
 * the authority — if the two disagree the address is wrong, and every child,
 * settings and back link built from it would point into an initiative the
 * entity isn't in. This is the rewrite that resolves that.
 */
import { describe, expect, it } from "vitest";

import { canonicalInitiativePath } from "@/lib/guildUrl";

describe("canonicalInitiativePath", () => {
  it("replaces an initiative the entity doesn't belong to", () => {
    expect(canonicalInitiativePath("/c/1/i/9/projects/7", 5)).toBe("/c/1/i/5/projects/7");
    expect(canonicalInitiativePath("/c/1/i/9/projects/7/tasks/22", 5)).toBe(
      "/c/1/i/5/projects/7/tasks/22"
    );
  });

  // An app's calendar belongs to no initiative; its address says so.
  it("drops the segment for a guild-level entity", () => {
    expect(canonicalInitiativePath("/c/1/i/9/calendars/2", null)).toBe("/c/1/calendars/2");
    expect(canonicalInitiativePath("/c/1/i/9/calendars/2/events/8", null)).toBe(
      "/c/1/calendars/2/events/8"
    );
  });

  it("inserts the segment when the entity does belong to one", () => {
    expect(canonicalInitiativePath("/c/1/calendars/2", 5)).toBe("/c/1/i/5/calendars/2");
  });

  it("leaves an already-correct path untouched", () => {
    expect(canonicalInitiativePath("/c/1/i/5/projects/7", 5)).toBe("/c/1/i/5/projects/7");
    expect(canonicalInitiativePath("/c/1/calendars/2", null)).toBe("/c/1/calendars/2");
  });

  // Nothing outside a guild has an initiative to canonicalize.
  it("leaves a non-guild path alone", () => {
    expect(canonicalInitiativePath("/my-projects", 5)).toBe("/my-projects");
    expect(canonicalInitiativePath("/profile/notifications", null)).toBe("/profile/notifications");
  });

  it("handles the guild root", () => {
    expect(canonicalInitiativePath("/c/1", 5)).toBe("/c/1/i/5");
    expect(canonicalInitiativePath("/c/1/i/5", null)).toBe("/c/1");
  });
});
