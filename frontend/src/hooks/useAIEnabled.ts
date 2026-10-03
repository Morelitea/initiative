import { useQuery } from "@tanstack/react-query";

import {
  getGetResolvedAiSettingsQueryKey,
  getResolvedAiSettings,
} from "@/api/generated/ai-settings/ai-settings";
import type { ResolvedAISettingsResponse } from "@/api/generated/initiativeAPI.schemas";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

/**
 * Whether AI features are available to the current member in the active community.
 *
 * AI resolution is community-scoped: the backend collapses the global mode, the
 * connection the member selected, and any key they attached into a single
 * `enabled` flag on `GET /c/{communityId}/settings/ai/resolved`. The member is AI
 * enabled exactly when that endpoint returns `enabled: true`, so we trust it
 * directly rather than re-deriving credential state on the client.
 */
export const useAIEnabled = () => {
  const communityId = useActiveCommunityId();
  const query = useQuery<ResolvedAISettingsResponse>({
    queryKey: getGetResolvedAiSettingsQueryKey(communityId),
    queryFn: () => getResolvedAiSettings(communityId),
    enabled: communityId > 0,
    staleTime: 5 * 60 * 1000,
  });

  return {
    isEnabled: Boolean(query.data?.enabled),
    isLoading: query.isLoading,
    data: query.data,
  };
};
