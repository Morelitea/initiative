/**
 * How a community's location reads.
 *
 * A location is a country and as much finer as the community's admin gave:
 * a region (a state, a province, a prefecture — whatever the country's first
 * division is), a city, a street address, a postcode, and a name of their own
 * for the place. Nothing here assumes one country's address form.
 *
 * Two readings come out of it:
 *
 * - **the line** — what a card or a banner shows, which has to fit one short
 *   row. It names the place at the coarsest grain that still says where it is
 *   ("Seattle, WA", "Lyon, France", "Ontario, Canada", "Japan"), behind the
 *   community's own name for it. Never the street, never the postcode.
 * - **the details** — everything that was given, for whoever asks to see it.
 *
 * Country names come from the browser (`Intl.DisplayNames`), so they are in
 * the reader's language and cost no data. The location library is only needed
 * to *pick* a place, in the settings editor.
 */

import type { GuildLocationOutput } from "@/api/generated/initiativeAPI.schemas";

export type GuildLocation = GuildLocationOutput;

/**
 * Countries whose regions are written as their code after a city
 * ("Seattle, WA", "Toronto, ON", "Perth, WA", "Recife, PE"). Elsewhere a
 * region's code means nothing to most readers, so a city is followed by its
 * country instead.
 */
const ABBREVIATED_REGION_COUNTRIES = new Set(["US", "CA", "AU", "BR"]);

/** Past this many characters a country's name gives way to its short form. */
const LONG_COUNTRY_NAME = 12;

const displayNames = new Map<string, Intl.DisplayNames | null>();

const regionNames = (locale: string, style: "long" | "short"): Intl.DisplayNames | null => {
  const key = `${locale}|${style}`;
  if (!displayNames.has(key)) {
    try {
      displayNames.set(key, new Intl.DisplayNames([locale, "en"], { type: "region", style }));
    } catch {
      displayNames.set(key, null);
    }
  }
  return displayNames.get(key) ?? null;
};

/** The country's name in the reader's language, or its code if unknown. */
export const countryName = (code: string, locale: string): string => {
  try {
    return regionNames(locale, "long")?.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
};

/**
 * The country as a line can afford it: its name, or its short form ("US",
 * "UK") when the name is long enough to crowd the place out.
 */
const countryForLine = (code: string, locale: string): string => {
  const long = countryName(code, locale);
  if (long.length <= LONG_COUNTRY_NAME) return long;
  try {
    return regionNames(locale, "short")?.of(code.toUpperCase()) ?? long;
  } catch {
    return long;
  }
};

/** A region code worth showing: short and letters only ("WA", not "06"). */
const usableRegionCode = (location: GuildLocation): string | null => {
  const code = location.region_code?.trim();
  if (!code || !ABBREVIATED_REGION_COUNTRIES.has(location.country.toUpperCase())) return null;
  return /^[A-Za-z]{1,3}$/.test(code) ? code.toUpperCase() : null;
};

/** The place, at the grain one row can carry — no label, no street. */
export const locationPlace = (location: GuildLocation, locale: string): string => {
  const city = location.city?.trim();
  const region = location.region?.trim();
  const regionCode = usableRegionCode(location);
  const country = countryForLine(location.country, locale);

  if (city) return `${city}, ${regionCode ?? country}`;
  if (region) return `${region}, ${country}`;
  return countryName(location.country, locale);
};

/** The whole line: the community's name for the place, then the place. */
export const locationLine = (location: GuildLocation, locale: string): string => {
  const place = locationPlace(location, locale);
  const label = location.label?.trim();
  return label ? `${label}, ${place}` : place;
};

/**
 * Everything that was given, one line each: the community's name for the
 * place, the street, the locality and its postcode, the country.
 */
export type LocationDetailLine = {
  part: "label" | "address" | "locality" | "country";
  text: string;
};

export const locationDetailLines = (
  location: GuildLocation,
  locale: string
): LocationDetailLine[] => {
  const lines: LocationDetailLine[] = [];
  const label = location.label?.trim();
  if (label) lines.push({ part: "label", text: label });
  const address = location.address?.trim();
  if (address) lines.push({ part: "address", text: address });
  const locality = [location.city?.trim(), location.region?.trim()].filter(Boolean).join(", ");
  const postal = location.postal_code?.trim();
  const localityLine = [locality, postal].filter(Boolean).join(" ");
  if (localityLine) lines.push({ part: "locality", text: localityLine });
  lines.push({ part: "country", text: countryName(location.country, locale) });
  return lines;
};

/**
 * Whether the details say more than the line does — a street, a postcode, or
 * a region or country the line left out. Only then is the line worth opening.
 */
export const locationHasMoreDetail = (location: GuildLocation): boolean => {
  if (location.address?.trim() || location.postal_code?.trim()) return true;
  const city = location.city?.trim();
  const region = location.region?.trim();
  // A city drops its region from the line, and a code stands in for the
  // country, so either way there is more to say.
  if (city && region) return true;
  if (city && usableRegionCode(location)) return true;
  return false;
};

/** Where a map can find it: everything given, as one search. */
export const locationMapUrl = (location: GuildLocation, locale: string): string => {
  const query = [
    location.address,
    location.city,
    location.region,
    location.postal_code,
    countryName(location.country, locale),
  ]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(", ");
  return `https://www.openstreetmap.org/search?query=${encodeURIComponent(query)}`;
};
