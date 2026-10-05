import { afterEach, describe, expect, it, vi } from "vitest";

import {
  effectiveNear,
  nearOfPlace,
  nearSearchFrom,
  parseSavedNear,
  placeOfNear,
  savedNearSnapshot,
  saveNear,
  subscribeSavedNear,
} from "./directoryNear";

afterEach(() => {
  saveNear(null, 1);
  saveNear(null, 2);
});

describe("nearSearchFrom", () => {
  it("keeps a well-formed place, upper-casing its codes", () => {
    expect(
      nearSearchFrom({ near_country: "us", near_region: "wa", near_city: " Seattle " })
    ).toEqual({ near_country: "US", near_region: "WA", near_city: "Seattle" });
  });

  it("drops the lot when the country is not a country code", () => {
    expect(nearSearchFrom({ near_country: "USA", near_city: "Seattle" })).toEqual({});
    expect(nearSearchFrom({ near_city: "Seattle" })).toEqual({});
  });
});

describe("nearOfPlace / placeOfNear", () => {
  it("reads an unpicked place as nowhere", () => {
    expect(nearOfPlace({ country: "", region: "", region_code: "", city: "" })).toBeNull();
  });

  it("round-trips a picked place", () => {
    const place = { country: "US", region: "Washington", region_code: "WA", city: "Seattle" };
    expect(placeOfNear(nearOfPlace(place))).toEqual(place);
  });
});

describe("the kept place", () => {
  it("is kept, told about, and cleared", () => {
    const heard = vi.fn();
    const stop = subscribeSavedNear(heard);

    saveNear({ country: "JP", city: "Kyoto" }, 1);
    expect(parseSavedNear(savedNearSnapshot(1))).toMatchObject({ country: "JP", city: "Kyoto" });

    saveNear(null, 1);
    expect(savedNearSnapshot(1)).toBeNull();
    expect(heard).toHaveBeenCalledTimes(2);
    stop();
  });

  it("is each account's own", () => {
    saveNear({ country: "JP", city: "Kyoto" }, 1);

    expect(savedNearSnapshot(2)).toBeNull();
    expect(savedNearSnapshot(null)).toBeNull();
    // Nobody signed in keeps nothing.
    saveNear({ country: "US" }, null);
    expect(savedNearSnapshot(null)).toBeNull();
  });

  it("gives way to a place in the address", () => {
    const kept = { country: "US", region: "WA", regionName: "Washington" };
    expect(effectiveNear({}, kept)).toBe(kept);
    expect(effectiveNear({ near_country: "JP" }, kept)).toEqual({
      country: "JP",
      region: undefined,
      city: undefined,
      regionName: undefined,
    });
    // The kept region's name still applies while the address names that region.
    expect(effectiveNear({ near_country: "US", near_region: "WA" }, kept)?.regionName).toBe(
      "Washington"
    );
  });
});
