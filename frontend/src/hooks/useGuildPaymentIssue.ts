import { useQuery } from "@tanstack/react-query";

import {
  getReadGuildPaymentIssueApiV1CommunitiesGuildIdBillingPaymentIssueGetQueryKey,
  readGuildPaymentIssueApiV1CommunitiesGuildIdBillingPaymentIssueGet,
} from "@/api/generated/communities/communities";
import type { CommunityPaymentIssueRead } from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

export const useGuildPaymentIssue = (
  guildId: number,
  options?: QueryOpts<CommunityPaymentIssueRead>
) =>
  useQuery<CommunityPaymentIssueRead>({
    queryKey:
      getReadGuildPaymentIssueApiV1CommunitiesGuildIdBillingPaymentIssueGetQueryKey(guildId),
    queryFn: () => readGuildPaymentIssueApiV1CommunitiesGuildIdBillingPaymentIssueGet(guildId),
    retry: false,
    staleTime: 60_000,
    ...options,
  });
