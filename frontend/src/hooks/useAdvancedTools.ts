import { useQuery } from "@tanstack/react-query";

import {
  getListAdvancedToolsApiV1GGuildIdAdvancedToolsGetQueryKey,
  listAdvancedToolsApiV1GGuildIdAdvancedToolsGet,
} from "@/api/generated/advanced-tools/advanced-tools";
import type {
  AdvancedToolListResponse,
  ListAdvancedToolsApiV1GGuildIdAdvancedToolsGetParams,
} from "@/api/generated/initiativeAPI.schemas";
import { useActiveGuildId } from "@/hooks/useActiveGuildId";

type QueryOpts = {
  enabled?: boolean;
  staleTime?: number;
};

/**
 * List the guild's advanced tools (optionally filtered to one initiative).
 * Rows are created/updated by the external automation service; this app owns
 * listing, sharing (DAC grants), and deletion (trash).
 */
export const useAdvancedToolsList = (
  params?: ListAdvancedToolsApiV1GGuildIdAdvancedToolsGetParams,
  options?: QueryOpts
) => {
  const guildId = useActiveGuildId();
  return useQuery<AdvancedToolListResponse>({
    queryKey: getListAdvancedToolsApiV1GGuildIdAdvancedToolsGetQueryKey(guildId, params),
    queryFn: () =>
      listAdvancedToolsApiV1GGuildIdAdvancedToolsGet(
        guildId,
        params
      ) as unknown as Promise<AdvancedToolListResponse>,
    ...options,
  });
};
