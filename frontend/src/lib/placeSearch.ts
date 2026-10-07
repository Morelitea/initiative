/**
 * Suggestions for a place being typed, from the cities `cities.json` knows
 * (GeoNames: every place of a thousand people or more, with its region and
 * point) and the countries the browser can name.
 *
 * Whatever is typed ahead of the place is kept: "1 Queen Anne Ave N, Seatt"
 * suggests "1 Queen Anne Ave N, Seattle, Washington, United States". Anything
 * typed after the place's name narrows it: "Paris, Texas", "Seattle, WA".
 * Places of one name come closest to the reader first.
 */

import { countriesNamedBy, countryName, fold } from "@/lib/communityLocation";
import type { Place } from "@/lib/directoryNear";

type CityRecord = { name: string; lat: string; lng: string; country: string; admin1: string };
type RegionRecord = { code: string; name: string };

type City = {
  name: string;
  /** The name, folded for comparing. */
  key: string;
  country: string;
  region: string | undefined;
  regionKey: string;
  /** The region's own code, folded ("wa"). */
  regionCode: string;
  latitude: number;
  longitude: number;
};

export type PlaceIndex = City[];

export type PlaceSuggestion = {
  /** The place alone, as the list shows it. */
  label: string;
  /** The whole field, once it is picked. */
  place: Place;
};

/** Typed before a city is looked for: one letter matches too much to help. */
const MIN_QUERY = 2;
/** Countries offered at once; a few letters rarely start more names than this. */
const COUNTRY_LIMIT = 3;

export const buildPlaceIndex = (cities: CityRecord[], regions: RegionRecord[]): PlaceIndex => {
  const regionNames = new Map(regions.map((region) => [region.code, region.name]));
  return cities.map((city) => {
    const region = regionNames.get(`${city.country}.${city.admin1}`);
    return {
      name: city.name,
      key: fold(city.name),
      country: city.country,
      region,
      regionKey: region ? fold(region) : "",
      regionCode: city.admin1.toLowerCase(),
      latitude: Number(city.lat),
      longitude: Number(city.lng),
    };
  });
};

export type Point = { latitude: number; longitude: number };

/** The city a time zone is named for, folded: "America/Los_Angeles" is "los angeles". */
const zoneCity = (timeZone: string): string =>
  fold((timeZone.split("/").pop() ?? "").replaceAll("_", " "));

/** The time zones a country keeps, where the browser can say (`getTimeZones`, or
 *  the `timeZones` it replaced); empty where it cannot. */
const zonesOf = (country: string): string[] => {
  try {
    const locale = new Intl.Locale(`und-${country}`) as Intl.Locale & {
      getTimeZones?: () => string[];
      timeZones?: string[];
    };
    return locale.getTimeZones?.() ?? locale.timeZones ?? [];
  } catch {
    return [];
  }
};

/**
 * Roughly where the reader is, from their browser's time zone: a zone is named
 * for a city ("America/Los_Angeles"). Of the places of that name, those in a
 * country that keeps the zone, where the browser can say which; of those, the
 * one whose longitude fits the zone's standard offset from UTC (fifteen
 * degrees an hour). Nothing for a zone that names no known city ("Etc/UTC").
 */
export const timeZoneOrigin = (
  index: PlaceIndex,
  timeZone: string,
  standardOffsetMinutes: number
): Point | null => {
  const key = zoneCity(timeZone);
  const named = index.filter((city) => city.key === key);
  if (!named.length) return null;
  // Zones are compared by their city: a browser may name one by an older alias.
  const keepers = named.filter((city) =>
    zonesOf(city.country).some((zone) => zoneCity(zone) === key)
  );
  // getTimezoneOffset() counts minutes behind UTC: -60 is UTC+1, so 15° east.
  const longitude = -standardOffsetMinutes / 4;
  const best = (keepers.length ? keepers : named).reduce((a, b) =>
    Math.abs(b.longitude - longitude) < Math.abs(a.longitude - longitude) ? b : a
  );
  return { latitude: best.latitude, longitude: best.longitude };
};

/** The reader's own `timeZoneOrigin`. */
export const browserOrigin = (index: PlaceIndex): Point | null => {
  try {
    const { timeZone } = Intl.DateTimeFormat().resolvedOptions();
    if (!timeZone) return null;
    // Summer time moves the clock, not the place: the standard offset is the
    // larger of a January and a July one, in either hemisphere.
    const year = new Date().getFullYear();
    const standard = Math.max(
      new Date(year, 0, 1).getTimezoneOffset(),
      new Date(year, 6, 1).getTimezoneOffset()
    );
    return timeZoneOrigin(index, timeZone, standard);
  } catch {
    return null;
  }
};

/** How far apart two points are, for ranking only: a flat-map approximation. */
const roughDistance = (from: Point, to: Point): number => {
  const dLat = to.latitude - from.latitude;
  // Wrapped, so the date line is not the far side of the world.
  const dLon = ((((to.longitude - from.longitude) % 360) + 540) % 360) - 180;
  const scale = Math.cos((((from.latitude + to.latitude) / 2) * Math.PI) / 180);
  return dLat * dLat + dLon * scale * (dLon * scale);
};

const cityLabel = (city: City, locale: string): string =>
  [
    city.name,
    city.region !== city.name ? city.region : undefined,
    countryName(city.country, locale),
  ]
    .filter(Boolean)
    .join(", ");

/**
 * What to offer for `text`. The place is looked for from the first comma
 * part on; the first part that starts a known name is the place, everything
 * before it stays as typed, and everything after it narrows the place to a
 * region or a country.
 */
export const suggestPlaces = (
  index: PlaceIndex,
  text: string,
  { locale, origin, limit }: { locale: string; origin?: Point | null; limit: number }
): PlaceSuggestion[] => {
  const parts = text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  for (let start = 0; start < parts.length; start += 1) {
    const head = fold(parts[start]);
    if (head.length < MIN_QUERY) continue;
    const qualifiers = parts.slice(start + 1).map((part) => {
      const folded = fold(part);
      return { folded, countries: new Set(countriesNamedBy(part, locale)) };
    });
    const cities = index.filter(
      (city) =>
        city.key.startsWith(head) &&
        qualifiers.every(
          (q) =>
            city.regionKey.startsWith(q.folded) ||
            city.regionCode === q.folded ||
            q.countries.has(city.country)
        )
    );
    const countries = qualifiers.length ? [] : countriesNamedBy(parts[start], locale);
    if (!cities.length && !countries.length) continue;

    // An exact name before a longer one, then the closest to the reader, then
    // the shortest and alphabetical.
    const distance = new Map(
      origin ? cities.map((city) => [city, roughDistance(origin, city)] as const) : []
    );
    cities.sort(
      (a, b) =>
        Number(b.key === head) - Number(a.key === head) ||
        (distance.get(a) ?? 0) - (distance.get(b) ?? 0) ||
        a.name.length - b.name.length ||
        a.name.localeCompare(b.name)
    );
    const before = parts.slice(0, start).join(", ");
    const withBefore = (label: string) => (before ? `${before}, ${label}` : label);
    const suggestions: PlaceSuggestion[] = countries.slice(0, COUNTRY_LIMIT).map((country) => {
      const label = countryName(country, locale);
      return {
        label,
        place: { text: withBefore(label), country, latitude: null, longitude: null },
      };
    });
    const seen = new Set(suggestions.map((suggestion) => suggestion.label));
    for (const city of cities) {
      if (suggestions.length >= limit) break;
      const label = cityLabel(city, locale);
      // Two places of one name in one region read the same; the first will do.
      if (seen.has(label)) continue;
      seen.add(label);
      suggestions.push({
        label,
        place: {
          text: withBefore(label),
          country: city.country,
          latitude: city.latitude,
          longitude: city.longitude,
        },
      });
    }
    return suggestions;
  }
  return [];
};
