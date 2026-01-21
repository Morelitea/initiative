import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import type { ResolvedAISettings } from "@/types/api";

export const useAIEnabled = () => {
  const query = useQuery<ResolvedAISettings>({
    queryKey: ["settings", "ai", "resolved"],
    queryFn: async () => {
      const response = await apiClient.get<ResolvedAISettings>("/settings/ai/resolved");
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });

  return {
    isEnabled: Boolean(query.data?.enabled && query.data?.has_api_key),
    isLoading: query.isLoading,
    data: query.data,
  };
};
