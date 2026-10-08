/**
 * How a community's location reads.
 *
 * A location is the place as its admin typed it — a country, a city, a full
 * street address — shown as typed, and the place it was pinned to from the
 * suggestions: a country, and for anywhere finer, its coordinates. The pin is
 * what puts a community near the people browsing for one.
 *
 * Country names come from the browser (`Intl.DisplayNames`), so they are in
 * the reader's language and cost no data.
 */

import type { CommunityLocationOutput } from "@/api/generated/initiativeAPI.schemas";

export type CommunityLocation = CommunityLocationOutput;

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

/** Where a map can find it: the pinned point, else the text as a search. */
export const locationMapUrl = (location: CommunityLocation): string => {
  const { latitude, longitude } = location;
  return latitude !== null && longitude !== null
    ? `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=13/${latitude}/${longitude}`
    : `https://www.openstreetmap.org/search?query=${encodeURIComponent(location.text)}`;
};

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
/** Two-letter region codes that are not countries anybody lives in. */
const NOT_COUNTRIES = new Set(["EU", "EZ", "UN", "ZZ", "QO"]);

/**
 * Whether a code is the one a country goes by, rather than a retired alias for
 * it ("UK" for GB, "DD" for DE), which the browser still names.
 */
const isCanonicalRegion = (code: string): boolean => {
  try {
    return Intl.getCanonicalLocales(`und-${code}`)[0] === `und-${code}`;
  } catch {
    return false;
  }
};

/** Text as a search compares it: no accents, no case, no edge spaces. */
export const fold = (text: string): string =>
  text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .trim();

/** Every country's names a reader might type, per locale: long and short. */
const countryNameIndex = new Map<string, { code: string; names: string[] }[]>();

const namesOfCountries = (locale: string) => {
  const cached = countryNameIndex.get(locale);
  if (cached) return cached;
  const index: { code: string; names: string[] }[] = [];
  const lookups = [locale, "en"].flatMap((lang) =>
    (["long", "short"] as const).map((style) => regionNames(lang, style))
  );
  for (const first of LETTERS) {
    for (const second of LETTERS) {
      const code = `${first}${second}`;
      if (NOT_COUNTRIES.has(code) || !isCanonicalRegion(code)) continue;
      const names = new Set<string>();
      for (const lookup of lookups) {
        let name: string | undefined;
        try {
          name = lookup?.of(code);
        } catch {
          name = undefined;
        }
        // An unknown code comes back as itself.
        if (name && name !== code) names.add(fold(name));
      }
      if (names.size) index.push({ code, names: [...names] });
    }
  }
  countryNameIndex.set(locale, index);
  return index;
};

/**
 * The countries a search names, as codes: "japan" is JP, "united" is every
 * United something, "uk" is GB. A location stores its country as a code, so
 * the directory's search needs these to find a community by its country.
 *
 * Two letters match a code or a short name exactly — "us" is the United
 * States, not every country with "us" in it. Longer text matches the start of
 * a name or of any word in one.
 */
export const countriesNamedBy = (query: string, locale: string): string[] => {
  const needle = fold(query);
  if (needle.length < 2) return [];
  const matches: string[] = [];
  for (const { code, names } of namesOfCountries(locale)) {
    const hit =
      needle.length === 2
        ? needle === code.toLowerCase() || names.includes(needle)
        : names.some(
            (name) =>
              name.startsWith(needle) ||
              name.split(/[\s-]+/).some((word) => word.startsWith(needle))
          );
    if (hit) matches.push(code);
  }
  return matches;
};
