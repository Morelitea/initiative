/**
 * The places a place field suggests from.
 *
 * `cities.json` is a few megabytes, so it is imported on demand rather than
 * with the app: only once somebody starts typing a place. It loads once and is
 * kept for the session.
 */

import { useQuery } from "@tanstack/react-query";

import { buildPlaceIndex } from "@/lib/placeSearch";

export const usePlaceIndex = (enabled: boolean) =>
  useQuery({
    queryKey: ["place-index"],
    queryFn: async () => {
      const [{ default: cities }, { default: regions }] = await Promise.all([
        import("cities.json"),
        import("cities.json/admin1"),
      ]);
      return buildPlaceIndex(cities, regions);
    },
    enabled,
    staleTime: Number.POSITIVE_INFINITY,
    gcTime: Number.POSITIVE_INFINITY,
  });
