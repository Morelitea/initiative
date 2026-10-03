import { useQuery } from "@tanstack/react-query";

import { getGetUserStatsQueryKey, getUserStats } from "@/api/generated/users/users";

export function useUserStats(guildId?: number | null) {
  const params = guildId ? { guild_id: guildId } : undefined;

  return useQuery({
    queryKey: getGetUserStatsQueryKey(params),
    queryFn: () => getUserStats(params),
    staleTime: 5 * 60 * 1000,
  });
}
