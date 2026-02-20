import { useQuery } from "@tanstack/react-query";

import {
  getUserStatsApiV1UsersMeStatsGet,
  getGetUserStatsApiV1UsersMeStatsGetQueryKey,
} from "@/api/generated/users/users";
import type { UserStatsResponse } from "@/api/generated/initiativeAPI.schemas";

export function useUserStats(guildId?: number | null) {
  const params = guildId ? { guild_id: guildId } : undefined;

  return useQuery({
    queryKey: getGetUserStatsApiV1UsersMeStatsGetQueryKey(params),
    queryFn: () =>
      getUserStatsApiV1UsersMeStatsGet(params) as unknown as Promise<UserStatsResponse>,
    staleTime: 5 * 60 * 1000,
  });
}
