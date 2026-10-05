/**
 * Where a reader of the community directory says they are.
 *
 * It sorts the directory — the communities nearest them first — and never
 * narrows it. It travels in the directory's address (`near_country`,
 * `near_region`, `near_city`, the same names the endpoint takes), and the last
 * one set is kept on this device for the account that set it, so the directory
 * opens near them next time too. A place in the address wins over the kept one.
 */

import { getItem, removeItem, setItem } from "@/lib/storage";

export type NearPlace = {
  /** ISO 3166-1 alpha-2. */
  country: string;
  /** The region's ISO 3166-2 suffix ("WA"). */
  region?: string;
  /** The region's name, for saying where; never sent. */
  regionName?: string;
  city?: string;
};

/** A place as a picker holds it: every part a string, empty for unpicked. */
export type Place = {
  /** ISO 3166-1 alpha-2, or empty for none picked. */
  country: string;
  region: string;
  /** The region's ISO 3166-2 suffix ("WA"). */
  region_code: string;
  city: string;
};

export const EMPTY_PLACE: Place = { country: "", region: "", region_code: "", city: "" };

const part = (value: unknown): string => (typeof value === "string" ? value : "");

/** A place as it was saved, on today's shape. */
export const placeFrom = (saved: unknown): Place => {
  if (!saved || typeof saved !== "object") return EMPTY_PLACE;
  const fields = saved as Record<string, unknown>;
  return {
    country: part(fields.country),
    region: part(fields.region),
    region_code: part(fields.region_code),
    city: part(fields.city),
  };
};

/** A picked place, as somewhere to sort the directory from; none if unpicked. */
export const nearOfPlace = (place: Place): NearPlace | null =>
  place.country
    ? {
        country: place.country,
        region: place.region_code || undefined,
        regionName: place.region || undefined,
        city: place.city.trim() || undefined,
      }
    : null;

/** The other way: a place to sort from, as a picker shows it. */
export const placeOfNear = (near: NearPlace | null): Place =>
  near
    ? {
        country: near.country,
        region: near.regionName ?? "",
        region_code: near.region ?? "",
        city: near.city ?? "",
      }
    : EMPTY_PLACE;

export type NearSearch = {
  near_country?: string;
  near_region?: string;
  near_city?: string;
};

/** Kept per account: another account on the same device has its own. */
const nearKey = (userId: number): string => `initiative-directory-near:${userId}`;

const text = (value: unknown, max: number): string | undefined =>
  typeof value === "string" && value.trim() ? value.trim().slice(0, max) : undefined;

/** The near-place parameters of an address, as far as they make sense. */
export const nearSearchFrom = (search: Record<string, unknown>): NearSearch => {
  const country = text(search.near_country, 3);
  if (!country || !/^[A-Za-z]{2}$/.test(country)) return {};
  const region = text(search.near_region, 10);
  const city = text(search.near_city, 100);
  return {
    near_country: country.toUpperCase(),
    ...(region ? { near_region: region.toUpperCase() } : {}),
    ...(city ? { near_city: city } : {}),
  };
};

/** A place, as the address carries it. */
export const nearSearchOf = (near: NearPlace | null): NearSearch =>
  near
    ? nearSearchFrom({ near_country: near.country, near_region: near.region, near_city: near.city })
    : {};

/** Every near-place parameter cleared, for an address that drops them. */
export const NO_NEAR_SEARCH: Record<keyof NearSearch, undefined> = {
  near_country: undefined,
  near_region: undefined,
  near_city: undefined,
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
export const parseSavedNear = (raw: string | null): NearPlace | null => {
  if (!raw) return null;
  try {
    const saved = JSON.parse(raw) as Partial<NearPlace>;
    const search = nearSearchOf(saved as NearPlace);
    if (!search.near_country) return null;
    return {
      country: search.near_country,
      region: search.near_region,
      city: search.near_city,
      regionName: text(saved.regionName, 100),
    };
  } catch {
    return null;
  }
};

export const saveNear = (near: NearPlace | null, userId: number | null): void => {
  if (userId === null) return;
  if (near?.country) void setItem(nearKey(userId), JSON.stringify(near));
  else void removeItem(nearKey(userId));
  for (const listener of listeners) listener();
};

/**
 * Where the directory is sorted from: the address's place, else the kept one.
 * A kept region name is used only while it still names the same region.
 */
export const effectiveNear = (search: NearSearch, saved: NearPlace | null): NearPlace | null => {
  if (!search.near_country) return saved;
  const sameRegion =
    saved && saved.country === search.near_country && saved.region === search.near_region;
  return {
    country: search.near_country,
    region: search.near_region,
    city: search.near_city,
    regionName: sameRegion ? saved.regionName : undefined,
  };
};
