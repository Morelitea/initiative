import { describe, expect, it } from "vitest";

import { resolveBadges, resolveDecoration } from "./profileDecorations";

describe("resolving a decoration", () => {
  it("finds the artwork an id names", () => {
    expect(resolveDecoration("core.aurora", "banner")?.src).toBe(
      "/decorations/banners/core-aurora.svg"
    );
  });

  it("has nothing for an id this build does not ship", () => {
    // What a profile wearing something from a later catalog gets: bare, not
    // broken, and not a request for a file that isn't there.
    expect(resolveDecoration("thirdparty.holo", "banner")).toBeUndefined();
  });

  it("will not hand a banner back as a frame", () => {
    expect(resolveDecoration("core.aurora", "frame")).toBeUndefined();
  });

  it("resolves nothing for an id built out of a path", () => {
    expect(resolveDecoration("../../../etc/passwd", "banner")).toBeUndefined();
  });

  it("keeps the badges it can draw, in the order they are worn", () => {
    const badges = resolveBadges({
      banner: null,
      frame: null,
      badges: ["spooky.lantern", "thirdparty.unknown", "core.fan"],
    });

    expect(badges.map((badge) => badge.id)).toEqual(["spooky.lantern", "core.fan"]);
  });

  it("draws nothing for a profile with no decorations at all", () => {
    expect(resolveBadges(null)).toEqual([]);
    expect(resolveDecoration(null, "frame")).toBeUndefined();
  });
});
