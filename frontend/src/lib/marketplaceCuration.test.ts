/**
 * The iPhone app shows the curated catalogue; every other platform shows it all.
 */
import { Capacitor } from "@capacitor/core";
import { describe, expect, it, vi } from "vitest";

import {
  catalogueSources,
  isCuratedSource,
  listingShownHere,
  showsCuratedCatalogueOnly,
} from "./marketplaceCuration";

describe("isCuratedSource", () => {
  it.each(["builtin", "registry"])("counts %s as curated", (source) => {
    expect(isCuratedSource(source)).toBe(true);
  });

  it.each(["operator", "local", "", null, undefined])("does not count %s", (source) => {
    expect(isCuratedSource(source)).toBe(false);
  });
});

describe("listingShownHere", () => {
  it("shows only curated listings on an iPhone", () => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue("ios");

    expect(showsCuratedCatalogueOnly()).toBe(true);
    expect(catalogueSources()).toEqual(["builtin", "registry"]);
    expect(listingShownHere({ source: "builtin" })).toBe(true);
    expect(listingShownHere({ source: "registry" })).toBe(true);
    expect(listingShownHere({ source: "operator" })).toBe(false);
    expect(listingShownHere({ source: "local" })).toBe(false);
  });

  it.each(["web", "android", "electron"])("shows everything on %s", (platform) => {
    vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform);

    expect(showsCuratedCatalogueOnly()).toBe(false);
    expect(catalogueSources()).toBeUndefined();
    expect(listingShownHere({ source: "operator" })).toBe(true);
    expect(listingShownHere({ source: "local" })).toBe(true);
  });
});
