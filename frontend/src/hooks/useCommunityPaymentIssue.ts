import { useQuery } from "@tanstack/react-query";

import {
  getReadCommunityPaymentIssueQueryKey,
  readCommunityPaymentIssue,
} from "@/api/generated/communities/communities";
import type { CommunityPaymentIssueRead } from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

export const useCommunityPaymentIssue = (
  communityId: number,
  options?: QueryOpts<CommunityPaymentIssueRead>
) =>
  useQuery<CommunityPaymentIssueRead>({
    queryKey: getReadCommunityPaymentIssueQueryKey(communityId),
    queryFn: () => readCommunityPaymentIssue(communityId),
    retry: false,
    staleTime: 60_000,
    ...options,
  });
