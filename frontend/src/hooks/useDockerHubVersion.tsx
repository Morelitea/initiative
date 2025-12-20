import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";

interface VersionResponse {
  version: string | null;
}

/**
 * Fetches the latest version tag from DockerHub via the backend API
 * Returns the latest semantic version tag (e.g., "0.3.1")
 */
export const useDockerHubVersion = () => {
  return useQuery<string | null>({
    queryKey: ["dockerhub-version"],
    queryFn: async () => {
      try {
        const response = await apiClient.get<VersionResponse>("/version/latest");
        return response.data.version;
      } catch (error) {
        console.error("Failed to fetch DockerHub version:", error);
        return null;
      }
    },
    staleTime: 1000 * 60 * 60, // 1 hour - don't check DockerHub too frequently
    gcTime: 1000 * 60 * 60 * 24, // 24 hours
    retry: 1, // Only retry once on failure
    refetchOnWindowFocus: false, // Don't refetch when window regains focus
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
