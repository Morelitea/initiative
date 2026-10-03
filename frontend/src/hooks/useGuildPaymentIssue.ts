import { useQuery } from "@tanstack/react-query";

import {
  getReadCommunityPaymentIssueQueryKey,
  readCommunityPaymentIssue,
} from "@/api/generated/communities/communities";
import type { CommunityPaymentIssueRead } from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

export const useGuildPaymentIssue = (
  guildId: number,
  options?: QueryOpts<CommunityPaymentIssueRead>
) =>
  useQuery<CommunityPaymentIssueRead>({
    queryKey: getReadCommunityPaymentIssueQueryKey(guildId),
    queryFn: () => readCommunityPaymentIssue(guildId),
    retry: false,
    staleTime: 60_000,
    ...options,
  });
