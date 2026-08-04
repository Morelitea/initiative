import { useQuery } from "@tanstack/react-query";

import {
  getGetResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGetQueryKey,
  getResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGet,
} from "@/api/generated/ai-settings/ai-settings";
import type { ResolvedAISettingsResponse } from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

/**
 * Whether AI features are available to the current member in the active guild.
 *
 * AI resolution is guild-scoped: the backend collapses the global mode, the
 * connection the member selected, and any key they attached into a single
 * `enabled` flag on `GET /g/{guildId}/settings/ai/resolved`. The member is AI
 * enabled exactly when that endpoint returns `enabled: true`, so we trust it
 * directly rather than re-deriving credential state on the client.
 */
export const useAIEnabled = () => {
  const guildId = useActiveGuildId();
  const query = useQuery<ResolvedAISettingsResponse>({
    queryKey: getGetResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGetQueryKey(guildId),
    queryFn: () => getResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGet(guildId),
    enabled: guildId > 0,
    staleTime: 5 * 60 * 1000,
  });

  return {
    isEnabled: Boolean(query.data?.enabled),
    isLoading: query.isLoading,
    data: query.data,
  };
};
