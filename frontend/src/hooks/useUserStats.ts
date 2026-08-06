import { useQuery } from "@tanstack/react-query";

import {
  getGetUserStatsApiV1MeStatsGetQueryKey,
  getUserStatsApiV1MeStatsGet,
} from "@/api/generated/users/users";

export function useUserStats(guildId?: number | null) {
  const params = guildId ? { guild_id: guildId } : undefined;

  return useQuery({
    queryKey: getGetUserStatsApiV1MeStatsGetQueryKey(params),
    queryFn: () => getUserStatsApiV1MeStatsGet(params),
    staleTime: 5 * 60 * 1000,
  });
}
