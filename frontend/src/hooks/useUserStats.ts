import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/api/client";
import type { UserStatsResponse } from "@/types/api";

export function useUserStats(guildId?: number | null) {
  return useQuery({
    queryKey: ["users", "me", "stats", guildId],
    queryFn: async () => {
      const params: Record<string, number> = {};
      if (guildId) {
        params.guild_id = guildId;
      }

      const response = await apiClient.get<UserStatsResponse>("/users/me/stats", { params });
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });
}
