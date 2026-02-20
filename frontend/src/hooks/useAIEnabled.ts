import { useQuery } from "@tanstack/react-query";

import {
  getResolvedAiSettingsApiV1SettingsAiResolvedGet,
  getGetResolvedAiSettingsApiV1SettingsAiResolvedGetQueryKey,
} from "@/api/generated/ai-settings/ai-settings";
import type { ResolvedAISettingsResponse } from "@/api/generated/initiativeAPI.schemas";

export const useAIEnabled = () => {
  const query = useQuery<ResolvedAISettingsResponse>({
    queryKey: getGetResolvedAiSettingsApiV1SettingsAiResolvedGetQueryKey(),
    queryFn: () =>
      getResolvedAiSettingsApiV1SettingsAiResolvedGet() as unknown as Promise<ResolvedAISettingsResponse>,
    staleTime: 5 * 60 * 1000,
  });

  return {
    isEnabled: Boolean(query.data?.enabled && query.data?.has_api_key),
    isLoading: query.isLoading,
    data: query.data,
  };
};
