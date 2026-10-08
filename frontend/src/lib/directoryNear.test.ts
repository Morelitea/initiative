import { afterEach, describe, expect, it, vi } from "vitest";

import {
  EMPTY_PLACE,
  effectiveNear,
  nearOfPlace,
  nearSearchFrom,
  nearSearchOf,
  parseSavedNear,
  placeFrom,
  savedNearSnapshot,
  saveNear,
  subscribeSavedNear,
} from "./directoryNear";

const seattle = {
  text: "Seattle, Washington, United States",
  country: "US",
  latitude: 47.6,
  longitude: -122.3,
};
const kyoto = { text: "Kyoto, Japan", country: "JP", latitude: 35.0, longitude: 135.8 };

afterEach(() => {
  saveNear(null, 1);
  saveNear(null, 2);
});

describe("nearSearchFrom", () => {
  it("keeps a well-formed place, and round-trips one", () => {
    expect(
      nearSearchFrom({
        near_country: "us",
        near_lat: "47.6",
        near_lon: -122.3,
        near_place: " Seattle ",
      })
    ).toEqual({ near_country: "US", near_lat: 47.6, near_lon: -122.3, near_place: "Seattle" });
    expect(effectiveNear(nearSearchOf(seattle), null)).toEqual(seattle);
  });

  it("drops what makes no sense: a bad country drops the lot, half a point the point", () => {
    expect(nearSearchFrom({ near_country: "USA", near_lat: 47.6, near_lon: -122.3 })).toEqual({});
    expect(nearSearchFrom({ near_lat: 47.6, near_lon: -122.3 })).toEqual({});
    expect(nearSearchFrom({ near_country: "US", near_lat: 47.6 })).toEqual({ near_country: "US" });
    expect(nearSearchFrom({ near_country: "US", near_lat: 91, near_lon: 0 })).toEqual({
      near_country: "US",
    });
  });
});

describe("placeFrom / nearOfPlace", () => {
  it("reads a place with no text, or none pinned, as nowhere to sort from", () => {
    // A sign-up draft saved before places were typed.
    expect(placeFrom({ country: "US", region: "WA", city: "Seattle" })).toEqual(EMPTY_PLACE);
    expect(nearOfPlace({ ...EMPTY_PLACE, text: "The old mill" })).toBeNull();
    expect(nearOfPlace(placeFrom(seattle))).toEqual(seattle);
  });
});

describe("the kept place", () => {
  it("is kept, told about, and cleared", () => {
    const heard = vi.fn();
    const stop = subscribeSavedNear(heard);

    saveNear(kyoto, 1);
    expect(parseSavedNear(savedNearSnapshot(1))).toEqual(kyoto);

    saveNear(null, 1);
    expect(savedNearSnapshot(1)).toBeNull();
    expect(heard).toHaveBeenCalledTimes(2);
    stop();
  });

  it("is each account's own", () => {
    saveNear(kyoto, 1);

    expect(savedNearSnapshot(2)).toBeNull();
    expect(savedNearSnapshot(null)).toBeNull();
    // Nobody signed in keeps nothing.
    saveNear(seattle, null);
    expect(savedNearSnapshot(null)).toBeNull();
  });

  it("gives way to a place in the address", () => {
    expect(effectiveNear({}, seattle)).toBe(seattle);
    expect(effectiveNear({ near_country: "JP" }, seattle)).toEqual({
      text: "",
      country: "JP",
      latitude: null,
      longitude: null,
    });
    // The kept words still apply while the address names the same place.
    expect(
      effectiveNear({ near_country: "US", near_lat: 47.6, near_lon: -122.3 }, seattle)?.text
    ).toBe(seattle.text);
  });
});
