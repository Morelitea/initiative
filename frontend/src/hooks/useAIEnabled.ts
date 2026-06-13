import { useQuery } from "@tanstack/react-query";

import {
  getGetResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGetQueryKey,
  getResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGet,
} from "@/api/generated/ai-settings/ai-settings";
import type { ResolvedAISettingsResponse } from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

export const useAIEnabled = () => {
  const guildId = useActiveGuildId();
  const query = useQuery<ResolvedAISettingsResponse>({
    queryKey: getGetResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGetQueryKey(guildId),
    queryFn: () =>
      getResolvedAiSettingsApiV1GGuildIdSettingsAiResolvedGet(
        guildId
      ) as unknown as Promise<ResolvedAISettingsResponse>,
    staleTime: 5 * 60 * 1000,
  });

  const data = query.data;
  // Ollama doesn't require an API key; every other provider does.
  const hasCredentials = data?.provider === "ollama" || Boolean(data?.has_api_key);

  return {
    isEnabled: Boolean(data?.enabled && hasCredentials),
    isLoading: query.isLoading,
    data,
  };
};
