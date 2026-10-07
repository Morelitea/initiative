import { describe, expect, it } from "vitest";

import { buildPlaceIndex, type Point, suggestPlaces, timeZoneOrigin } from "./placeSearch";

const index = buildPlaceIndex(
  [
    { name: "Seattle", lat: "47.60621", lng: "-122.33207", country: "US", admin1: "WA" },
    { name: "Seattle Hill", lat: "47.86", lng: "-122.17", country: "US", admin1: "WA" },
    { name: "Paris", lat: "48.85341", lng: "2.3488", country: "FR", admin1: "11" },
    { name: "Paris", lat: "33.66094", lng: "-95.55551", country: "US", admin1: "TX" },
    { name: "London", lat: "51.50853", lng: "-0.12574", country: "GB", admin1: "ENG" },
    { name: "London", lat: "37.12898", lng: "-84.08326", country: "US", admin1: "KY" },
    { name: "Buenos Aires", lat: "-34.61315", lng: "-58.37723", country: "AR", admin1: "07" },
    { name: "Buenos Aires", lat: "-7.72306", lng: "-35.3263", country: "BR", admin1: "30" },
    { name: "Tokyo", lat: "35.6895", lng: "139.69171", country: "JP", admin1: "40" },
    { name: "München", lat: "48.13743", lng: "11.57549", country: "DE", admin1: "02" },
  ],
  [
    { code: "US.WA", name: "Washington" },
    { code: "US.TX", name: "Texas" },
    { code: "GB.ENG", name: "England" },
    { code: "US.KY", name: "Kentucky" },
    { code: "FR.11", name: "Île-de-France" },
    { code: "JP.40", name: "Tokyo" },
    { code: "DE.02", name: "Bavaria" },
  ]
);

const labels = (text: string, origin?: Point | null) =>
  suggestPlaces(index, text, { locale: "en", origin, limit: 8 }).map((s) => s.label);

const seattle = { latitude: 47.6, longitude: -122.3 };
const berlin = { latitude: 52.5, longitude: 13.4 };

describe("suggestPlaces", () => {
  it("suggests places by the start of their name, pinned to their point", () => {
    expect(labels("seat")).toEqual([
      "Seattle, Washington, United States",
      "Seattle Hill, Washington, United States",
    ]);
    expect(suggestPlaces(index, "seattle", { locale: "en", limit: 8 })[0].place).toEqual({
      text: "Seattle, Washington, United States",
      country: "US",
      latitude: 47.60621,
      longitude: -122.33207,
    });
    // Accents are not needed, and a region of the place's own name is said once.
    expect(labels("munchen")).toEqual(["München, Bavaria, Germany"]);
    expect(labels("toky")).toEqual(["Tokyo, Japan"]);
  });

  it("puts the places closest to the reader first, and narrows by what follows the name", () => {
    expect(labels("paris", seattle)).toEqual([
      "Paris, Texas, United States",
      "Paris, Île-de-France, France",
    ]);
    expect(labels("paris", berlin)).toEqual([
      "Paris, Île-de-France, France",
      "Paris, Texas, United States",
    ]);
    expect(labels("Paris, France", seattle)).toEqual(["Paris, Île-de-France, France"]);
    expect(labels("Paris, TX")).toEqual(["Paris, Texas, United States"]);
  });

  it("offers a country alone, pinned to the country", () => {
    const [japan] = suggestPlaces(index, "Jap", { locale: "en", limit: 8 });
    expect(japan.place).toEqual({ text: "Japan", country: "JP", latitude: null, longitude: null });
  });

  it("keeps what was typed ahead of the place", () => {
    const [first] = suggestPlaces(index, "1 Queen Anne Ave N, Seattle, WA", {
      locale: "en",
      limit: 8,
    });
    expect(first.place.text).toBe("1 Queen Anne Ave N, Seattle, Washington, United States");
  });

  it("finds where the reader is from their time zone, by the city it names", () => {
    // Of the two Londons, the one at the zone's longitude.
    expect(timeZoneOrigin(index, "Europe/London", 0)).toEqual({
      latitude: 51.50853,
      longitude: -0.12574,
    });
    // A zone whose offset fits another country's place of that name better.
    expect(timeZoneOrigin(index, "America/Argentina/Buenos_Aires", 180)).toEqual({
      latitude: -34.61315,
      longitude: -58.37723,
    });
    expect(timeZoneOrigin(index, "America/Los_Angeles", 480)).toBeNull();
    expect(timeZoneOrigin(index, "Etc/UTC", 0)).toBeNull();
  });

  it("suggests nothing for a place it does not know", () => {
    expect(labels("The old mill")).toEqual([]);
  });
});
