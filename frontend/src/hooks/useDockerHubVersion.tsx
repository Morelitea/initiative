import { useQuery } from "@tanstack/react-query";

import {
  getLatestDockerhubVersionApiV1VersionLatestGet,
  getGetLatestDockerhubVersionApiV1VersionLatestGetQueryKey,
} from "@/api/generated/version/version";

interface VersionResponse {
  version: string | null;
}

/**
 * Fetches the latest version tag from DockerHub via the backend API
 * Returns the latest semantic version tag (e.g., "0.3.1")
 */
export const useDockerHubVersion = () => {
  return useQuery<string | null>({
    queryKey: getGetLatestDockerhubVersionApiV1VersionLatestGetQueryKey(),
    queryFn: async () => {
      try {
        const result =
          (await getLatestDockerhubVersionApiV1VersionLatestGet()) as unknown as VersionResponse;
        return result.version;
      } catch (error) {
        console.error("Failed to fetch DockerHub version:", error);
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
 * Compares two semantic version strings
 * Returns: -1 if v1 < v2, 0 if equal, 1 if v1 > v2
 */
export const compareVersions = (v1: string, v2: string): number => {
  const parts1 = v1.split(".").map(Number);
  const parts2 = v2.split(".").map(Number);

  for (let i = 0; i < 3; i++) {
    const num1 = parts1[i] || 0;
    const num2 = parts2[i] || 0;

    if (num1 > num2) return 1;
    if (num1 < num2) return -1;
  }

  return 0;
};
