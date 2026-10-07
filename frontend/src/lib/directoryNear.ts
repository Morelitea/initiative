/**
 * A place someone typed, and where a reader of the community directory is.
 *
 * Where the reader is sorts the directory — the communities nearest them
 * first — and never narrows it. It travels in the directory's address
 * (`near_country`, `near_lat`, `near_lon`, the names the endpoint takes, and
 * `near_place`, the words to show it by), and the last one set is kept on this
 * device for the account that set it, so the directory opens near them next
 * time too. A place in the address wins over the kept one.
 */

import { getItem, removeItem, setItem } from "@/lib/storage";

/** A place as a place field holds it: what was typed, and what it was pinned to. */
export type Place = {
  /** As typed, and as shown. */
  text: string;
  /** ISO 3166-1 alpha-2 of the pinned place; empty when nothing is pinned. */
  country: string;
  /** The pinned point; null for a country alone, or nothing pinned. */
  latitude: number | null;
  longitude: number | null;
};

export const EMPTY_PLACE: Place = { text: "", country: "", latitude: null, longitude: null };

/** The server's limit on a place's text. */
export const PLACE_TEXT_MAX = 200;

const isCountry = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z]{2}$/.test(value);

const coordinate = (value: unknown, bound: number): number | null => {
  const number = typeof value === "string" && value.trim() ? Number(value) : value;
  return typeof number === "number" && Number.isFinite(number) && Math.abs(number) <= bound
    ? number
    : null;
};

/** A place from its parts as they were kept, with whatever makes no sense left out. */
const placeOf = (text: unknown, country: unknown, latitude: unknown, longitude: unknown) => {
  const lat = coordinate(latitude, 90);
  const lon = coordinate(longitude, 180);
  const pinned = isCountry(country);
  // A point is kept only whole, and only within a country.
  const point = pinned && lat !== null && lon !== null;
  return {
    text: typeof text === "string" ? text.trim().slice(0, PLACE_TEXT_MAX) : "",
    country: pinned ? country.toUpperCase() : "",
    latitude: point ? lat : null,
    longitude: point ? lon : null,
  };
};

/** A place as it was saved, on today's shape. Older shapes had no text, and
 *  a place with no text is no place. */
export const placeFrom = (saved: unknown): Place => {
  if (!saved || typeof saved !== "object") return EMPTY_PLACE;
  const fields = saved as Record<string, unknown>;
  const place = placeOf(fields.text, fields.country, fields.latitude, fields.longitude);
  return place.text ? place : EMPTY_PLACE;
};

/** A place, as somewhere to sort the directory from: it needs a country. */
export const nearOfPlace = (place: Place): Place | null =>
  place.country && place.text.trim() ? place : null;

export type NearSearch = {
  near_country?: string;
  near_lat?: number;
  near_lon?: number;
  near_place?: string;
};

/** Kept per account: another account on the same device has its own. */
const nearKey = (userId: number): string => `initiative-directory-near:${userId}`;

/** The near-place parameters of an address, as far as they make sense. */
export const nearSearchFrom = (search: Record<string, unknown>): NearSearch => {
  const place = placeOf(search.near_place, search.near_country, search.near_lat, search.near_lon);
  if (!place.country) return {};
  return {
    near_country: place.country,
    ...(place.latitude !== null && place.longitude !== null
      ? { near_lat: place.latitude, near_lon: place.longitude }
      : {}),
    ...(place.text ? { near_place: place.text } : {}),
  };
};

/** A place, as the address carries it. */
export const nearSearchOf = (near: Place | null): NearSearch =>
  near
    ? nearSearchFrom({
        near_country: near.country,
        near_lat: near.latitude,
        near_lon: near.longitude,
        near_place: near.text,
      })
    : {};

/** Every near-place parameter cleared, for an address that drops them. */
export const NO_NEAR_SEARCH: Record<keyof NearSearch, undefined> = {
  near_country: undefined,
  near_lat: undefined,
  near_lon: undefined,
  near_place: undefined,
};

/** Who to tell when the kept place changes. */
const listeners = new Set<() => void>();

/** For `useSyncExternalStore`: hear about the kept place changing. */
export const subscribeSavedNear = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** The account's kept place, as stored — stable by value, for
 *  `useSyncExternalStore`. Nothing is kept for nobody. */
export const savedNearSnapshot = (userId: number | null): string | null =>
  userId === null ? null : getItem(nearKey(userId));

/** The kept place, read from what `savedNearSnapshot` returned. */
export const parseSavedNear = (raw: string | null): Place | null => {
  if (!raw) return null;
  try {
    return nearOfPlace(placeFrom(JSON.parse(raw)));
  } catch {
    return null;
  }
};

export const saveNear = (near: Place | null, userId: number | null): void => {
  if (userId === null) return;
  if (near?.country) void setItem(nearKey(userId), JSON.stringify(near));
  else void removeItem(nearKey(userId));
  for (const listener of listeners) listener();
};

/**
 * Where the directory is sorted from: the address's place, else the kept one.
 * An address without the words for its place borrows the kept place's while
 * the two are the same place.
 */
export const effectiveNear = (search: NearSearch, saved: Place | null): Place | null => {
  if (!search.near_country) return saved;
  const latitude = search.near_lat ?? null;
  const longitude = search.near_lon ?? null;
  const samePlace =
    saved &&
    saved.country === search.near_country &&
    saved.latitude === latitude &&
    saved.longitude === longitude;
  return {
    text: search.near_place ?? (samePlace ? saved.text : ""),
    country: search.near_country,
    latitude,
    longitude,
  };
};
