/**
 * The third-party licence notices every build writes beside index.html (see
 * scripts/third-party-notices.mjs).
 *
 * Read from the app's own origin, not the API: in the phone apps the file is
 * inside the bundle, which the WebView serves from its origin root. The path is
 * absolute for that reason; relative, it would resolve against the route.
 * The query key is not an API path, so the offline cache leaves it out.
 */

import { useQuery } from "@tanstack/react-query";

export const THIRD_PARTY_NOTICES_URL = "/THIRD_PARTY_NOTICES.txt";

export const useThirdPartyNotices = () =>
  useQuery({
    queryKey: ["third-party-notices"],
    queryFn: async () => {
      const response = await fetch(THIRD_PARTY_NOTICES_URL);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.text();
    },
    // It changes only with the bundle, and a new bundle is a reload.
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });
