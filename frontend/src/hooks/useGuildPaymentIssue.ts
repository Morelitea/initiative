import { useQuery } from "@tanstack/react-query";

import {
  getReadGuildPaymentIssueApiV1GuildsGuildIdBillingPaymentIssueGetQueryKey,
  readGuildPaymentIssueApiV1GuildsGuildIdBillingPaymentIssueGet,
} from "@/api/generated/guilds/guilds";
import type { GuildPaymentIssueRead } from "@/api/generated/initiativeAPI.schemas";
import type { QueryOpts } from "@/types/query";

export const useGuildPaymentIssue = (guildId: number, options?: QueryOpts<GuildPaymentIssueRead>) =>
  useQuery<GuildPaymentIssueRead>({
    queryKey: getReadGuildPaymentIssueApiV1GuildsGuildIdBillingPaymentIssueGetQueryKey(guildId),
    queryFn: () => readGuildPaymentIssueApiV1GuildsGuildIdBillingPaymentIssueGet(guildId),
    retry: false,
    staleTime: 60_000,
    ...options,
  });
