import { useQuery } from "@tanstack/react-query";

import { getGetUserStatsQueryKey, getUserStats } from "@/api/generated/users/users";

export function useUserStats(communityId?: number | null) {
  const params = communityId ? { community_id: communityId } : undefined;

  return useQuery({
    queryKey: getGetUserStatsQueryKey(params),
    queryFn: () => getUserStats(params),
    staleTime: 5 * 60 * 1000,
  });
}
