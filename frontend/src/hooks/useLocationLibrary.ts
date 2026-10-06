/**
 * The place library behind the community location editor.
 *
 * `country-state-city` is imported on demand rather than with the app: the
 * countries and their regions are a few hundred kilobytes, the cities several
 * megabytes, and only the settings editor ever needs them. Each loads once and
 * is kept for the session.
 */

import { useQuery } from "@tanstack/react-query";

/** Countries and their regions: small enough to fetch with the editor. */
export const useLocationPlaces = () =>
  useQuery({
    queryKey: ["location-library", "places"],
    queryFn: async () => {
      const [{ default: Country }, { default: State }] = await Promise.all([
        import("country-state-city/lib/country"),
        import("country-state-city/lib/state"),
      ]);
      return { countries: Country.getAllCountries(), State };
    },
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
  });

/** Every city the library knows — only once somebody asks to pick one. */
export const useLocationCities = (enabled: boolean) =>
  useQuery({
    queryKey: ["location-library", "cities"],
    queryFn: async () => (await import("country-state-city/lib/city")).default,
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
  });
