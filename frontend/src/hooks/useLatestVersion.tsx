import { useQuery } from "@tanstack/react-query";

import {
  getGetLatestReleaseVersionQueryKey,
  getLatestReleaseVersion,
} from "@/api/generated/version/version";

/**
 * Fetches the latest released version via the backend API
 * Returns the latest semantic version tag (e.g., "0.3.1")
 */
export const useLatestVersion = () => {
  return useQuery<string | null>({
    queryKey: getGetLatestReleaseVersionQueryKey(),
    queryFn: async () => {
      try {
        const result = await getLatestReleaseVersion();
        return result.version;
      } catch (error) {
        console.error("Failed to fetch the latest version:", error);
        return null;
      }
    },
    staleTime: 1000 * 60 * 60,
    gcTime: 1000 * 60 * 60 * 24,
    retry: 1,
    refetchOnWindowFocus: false,
  });
};

/**
 * Compare two versions: -1, 0 or 1.
 *
 * Each of major.minor.patch is read up to its first non-digit, and a version
 * with a suffix (`0.72.3-dev-abc`) comes before the same version without one.
 */
export const compareVersions = (v1: string, v2: string): number => {
  const parse = (version: string) => {
    const [core, ...suffix] = version.split("-");
    return {
      parts: core.split(".").map((part) => Number.parseInt(part, 10) || 0),
      suffix: suffix.join("-"),
    };
  };
  const a = parse(v1);
  const b = parse(v2);
  for (let i = 0; i < 3; i++) {
    const diff = (a.parts[i] ?? 0) - (b.parts[i] ?? 0);
    if (diff !== 0) return diff > 0 ? 1 : -1;
  }
  if (a.suffix === b.suffix) return 0;
  if (!a.suffix) return 1;
  if (!b.suffix) return -1;
  return a.suffix < b.suffix ? -1 : 1;
};
