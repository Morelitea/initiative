import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { DECORATIONS, resolveDecoration, resolveTrophies } from "./profileDecorations";

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

  it("keeps the trophies it can draw, in the order they are worn", () => {
    const trophies = resolveTrophies({
      banner: null,
      frame: null,
      trophies: ["spooky.lantern", "thirdparty.unknown", "core.fan"],
    });

    expect(trophies.map((badge) => badge.id)).toEqual(["spooky.lantern", "core.fan"]);
  });

  it("draws nothing for a profile with no decorations at all", () => {
    expect(resolveTrophies(null)).toEqual([]);
    expect(resolveDecoration(null, "frame")).toBeUndefined();
  });
});

/**
 * The two ends of a decoration have to meet, and nothing at runtime says so: a
 * pack's manifest names ids, this catalog maps an id to a file, and the file is
 * fetched by a browser that reports a missing one as a broken image nobody sees
 * in review. So both joins are checked here instead.
 */
describe("the catalog and what it names", () => {
  it("ships artwork for every decoration it lists", () => {
    const missing = Object.values(DECORATIONS)
      .map((decoration) => decoration.src)
      // A dated decoration is drawn in the client with the wearer's year
      // written into it, so its artwork is a data URI rather than a file.
      .filter((src) => !src.startsWith("data:"))
      .filter((src) => !existsSync(join(process.cwd(), "public", src)));

    expect(missing).toEqual([]);
  });

  it("draws every decoration the shipped packs grant", () => {
    const catalog = join(process.cwd(), "..", "backend", "app", "marketplace_catalog");
    const unknown: string[] = [];

    for (const file of readdirSync(catalog).filter((name) => name.endsWith(".json"))) {
      const manifest = JSON.parse(readFileSync(join(catalog, file), "utf8"));
      if (manifest.kind !== "profile_pack") continue;
      for (const declared of manifest.definition.decorations) {
        const known = DECORATIONS[declared.id];
        if (!known || known.kind !== declared.slot) unknown.push(`${file}: ${declared.id}`);
      }
    }

    expect(unknown).toEqual([]);
  });

  it("ships the picture every pack puts on its card", () => {
    // A pack's avatar is a path in the manifest rather than an id, so nothing
    // else here checks it — and a decoration leaving the pack is exactly when
    // it goes stale.
    const catalog = join(process.cwd(), "..", "backend", "app", "marketplace_catalog");
    const missing: string[] = [];

    for (const file of readdirSync(catalog).filter((name) => name.endsWith(".json"))) {
      const manifest = JSON.parse(readFileSync(join(catalog, file), "utf8"));
      if (manifest.kind !== "profile_pack" || !manifest.avatar_url) continue;
      if (!existsSync(join(process.cwd(), "public", manifest.avatar_url))) {
        missing.push(`${file}: ${manifest.avatar_url}`);
      }
    }

    expect(missing).toEqual([]);
  });
});
