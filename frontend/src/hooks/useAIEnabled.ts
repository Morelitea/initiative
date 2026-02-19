import { useQuery } from "@tanstack/react-query";

import {
  getResolvedAiSettingsApiV1SettingsAiResolvedGet,
  getGetResolvedAiSettingsApiV1SettingsAiResolvedGetQueryKey,
} from "@/api/generated/ai-settings/ai-settings";
import type { ResolvedAISettings } from "@/types/api";

export const useAIEnabled = () => {
  const query = useQuery<ResolvedAISettings>({
    queryKey: getGetResolvedAiSettingsApiV1SettingsAiResolvedGetQueryKey(),
    queryFn: () =>
      getResolvedAiSettingsApiV1SettingsAiResolvedGet() as unknown as Promise<ResolvedAISettings>,
    staleTime: 5 * 60 * 1000,
  });

  return {
    isEnabled: Boolean(query.data?.enabled && query.data?.has_api_key),
    isLoading: query.isLoading,
    data: query.data,
  };
};
