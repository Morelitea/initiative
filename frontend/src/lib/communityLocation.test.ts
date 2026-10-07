import { describe, expect, it } from "vitest";

import { type CommunityLocation, countriesNamedBy, locationMapUrl } from "./communityLocation";

const at = (parts: Partial<CommunityLocation> & { text: string }): CommunityLocation => ({
  label: null,
  country: null,
  latitude: null,
  longitude: null,
  ...parts,
});

describe("locationMapUrl", () => {
  it("opens the pinned point, and searches for the text of an unpinned place", () => {
    const pinned = at({ text: "Seattle", country: "US", latitude: 47.6, longitude: -122.3 });
    expect(locationMapUrl(pinned)).toBe(
      "https://www.openstreetmap.org/?mlat=47.6&mlon=-122.3#map=13/47.6/-122.3"
    );
    expect(locationMapUrl(at({ text: "The old mill, Leeds", label: "Knitters" }))).toBe(
      "https://www.openstreetmap.org/search?query=The%20old%20mill%2C%20Leeds"
    );
  });
});

describe("countriesNamedBy", () => {
  it("finds a country by its name", () => {
    expect(countriesNamedBy("Japan", "en")).toEqual(["JP"]);
  });

  it("finds it by a word of the name, and by every country sharing it", () => {
    const united = countriesNamedBy("united", "en");
    expect(united).toContain("US");
    expect(united).toContain("GB");
    expect(countriesNamedBy("kingdom", "en")).toContain("GB");
  });

  it("reads two letters as a code or a short name, not a fragment", () => {
    expect(countriesNamedBy("us", "en")).toEqual(["US"]);
    expect(countriesNamedBy("uk", "en")).toEqual(["GB"]);
  });

  it("takes the reader's language and English alike, accents or not", () => {
    expect(countriesNamedBy("Deutschland", "de")).toEqual(["DE"]);
    expect(countriesNamedBy("Germany", "de")).toEqual(["DE"]);
    expect(countriesNamedBy("Mexico", "es")).toEqual(["MX"]);
  });

  it("names nothing for a place that is not a country", () => {
    expect(countriesNamedBy("Seattle", "en")).toEqual([]);
    expect(countriesNamedBy("a", "en")).toEqual([]);
  });
});
