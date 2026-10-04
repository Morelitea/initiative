import { describe, expect, it } from "vitest";

import {
  countriesNamedBy,
  type GuildLocation,
  locationDetailLines,
  locationHasMoreDetail,
  locationLine,
  locationMapUrl,
} from "./guildLocation";

const at = (parts: Partial<GuildLocation> & { country: string }): GuildLocation => ({
  region: null,
  region_code: null,
  city: null,
  address: null,
  postal_code: null,
  label: null,
  ...parts,
});

describe("locationLine", () => {
  it("names a country on its own in full", () => {
    expect(locationLine(at({ country: "US" }), "en")).toBe("United States");
  });

  it("writes a US city with its state's code", () => {
    const seattle = at({ country: "US", region: "Washington", region_code: "WA", city: "Seattle" });
    expect(locationLine(seattle, "en")).toBe("Seattle, WA");
  });

  it("puts the community's own name for the place first", () => {
    const queenAnne = at({
      country: "US",
      region: "Washington",
      region_code: "WA",
      city: "Seattle",
      label: "Queen Anne Neighborhood",
    });
    expect(locationLine(queenAnne, "en")).toBe("Queen Anne Neighborhood, Seattle, WA");
  });

  it("follows a city with its country where regions are not written as codes", () => {
    const lyon = at({
      country: "FR",
      region: "Auvergne-Rhône-Alpes",
      region_code: "ARA",
      city: "Lyon",
    });
    expect(locationLine(lyon, "en")).toBe("Lyon, France");
  });

  it("shortens a long country name", () => {
    expect(locationLine(at({ country: "GB", city: "Leeds" }), "en")).toBe("Leeds, UK");
  });

  it("names a region with its country", () => {
    const ontario = at({ country: "CA", region: "Ontario", region_code: "ON" });
    expect(locationLine(ontario, "en")).toBe("Ontario, Canada");
  });

  it("never carries the street or the postcode", () => {
    const exact = at({
      country: "US",
      region: "Washington",
      region_code: "WA",
      city: "Seattle",
      address: "1 Queen Anne Ave N",
      postal_code: "98109",
    });
    expect(locationLine(exact, "en")).toBe("Seattle, WA");
  });

  it("reads the country in the reader's language", () => {
    expect(locationLine(at({ country: "DE" }), "de")).toBe("Deutschland");
  });
});

describe("locationHasMoreDetail", () => {
  it("is false when the line already says everything", () => {
    expect(locationHasMoreDetail(at({ country: "JP" }))).toBe(false);
    expect(locationHasMoreDetail(at({ country: "FR", city: "Lyon" }))).toBe(false);
  });

  it("is true for a street address or a postcode", () => {
    expect(locationHasMoreDetail(at({ country: "JP", address: "1-1 Chiyoda" }))).toBe(true);
    expect(locationHasMoreDetail(at({ country: "JP", postal_code: "100-0001" }))).toBe(true);
  });

  it("is true when the line left the region or the country out", () => {
    expect(locationHasMoreDetail(at({ country: "FR", region: "Bretagne", city: "Rennes" }))).toBe(
      true
    );
    expect(locationHasMoreDetail(at({ country: "US", region_code: "WA", city: "Seattle" }))).toBe(
      true
    );
  });
});

describe("locationDetailLines", () => {
  it("lists everything that was given", () => {
    const exact = at({
      country: "US",
      region: "Washington",
      region_code: "WA",
      city: "Seattle",
      address: "1 Queen Anne Ave N",
      postal_code: "98109",
      label: "Queen Anne Neighborhood",
    });
    expect(locationDetailLines(exact, "en").map((line) => line.text)).toEqual([
      "Queen Anne Neighborhood",
      "1 Queen Anne Ave N",
      "Seattle, Washington 98109",
      "United States",
    ]);
  });
});

describe("locationMapUrl", () => {
  it("searches for the whole place, without the community's label", () => {
    const url = locationMapUrl(at({ country: "US", city: "Seattle", label: "Queen Anne" }), "en");
    expect(url).toBe("https://www.openstreetmap.org/search?query=Seattle%2C%20United%20States");
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
